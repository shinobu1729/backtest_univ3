from abc import ABC, abstractmethod
import numpy as np
import typing as tp
import copy

from mellow_sdk.uniswap_utils import UniswapLiquidityAligner
from mellow_sdk.positions import UniV3Position, BiCurrencyPosition
from mellow_sdk.primitives import Pool, MIN_TICK, MAX_TICK


class AbstractStrategy(ABC):
    """
    ``AbstractStrategy`` is an abstract class for Strategies.

    Attributes:
        name: Unique name for the instance.
    """

    def __init__(self, name: str = None):
        if name is None:
            self.name = self.__class__.__name__
        else:
            self.name = name

    @abstractmethod
    def rebalance(self, *args, **kwargs) -> tp.Optional[str]:
        """
        Rebalance implementation.

        Args:
            args: Any args.
            kwargs: Any kwargs.

        Returns:
            Name of event or None if there was no event.
        """
        raise Exception(NotImplemented)


class Hold(AbstractStrategy):
    """
    ``Hold`` is the passive strategy buy and hold.
    """

    def __init__(self, name: str = None):
        super().__init__(name)
        self.prev_gain_date = None

    def rebalance(self, *args, **kwargs):
        timestamp = kwargs["record"]["timestamp"]
        portfolio = kwargs["portfolio"]

        if self.prev_gain_date is None:
            self.prev_gain_date = timestamp.date()

            bi_cur = BiCurrencyPosition(
                name=f"Vault",
                swap_fee=0,
                gas_cost=0,
                x=1,
                y=1,
                x_interest=0,
                y_interest=0,
            )

            portfolio.append(bi_cur)

        if timestamp.date() > self.prev_gain_date:
            vault = portfolio.get_position("Vault")
            vault.interest_gain(timestamp.date())
            self.prev_gain_date = timestamp.date()


class UniV3Passive(AbstractStrategy):
    """
    ``UniV3Passive`` is the passive strategy on UniswapV3, i.e. mint one interval and wait.

    Attributes:
        lower_price: Lower bound of the interval
        upper_price: Upper bound of the interval
        gas_cost: Gas costs, expressed in currency
        pool: UniswapV3 Pool instance
        name: Unique name for the instance
    """

    def __init__(
        self,
        lower_price: float,
        upper_price: float,
        pool: Pool,
        gas_cost: float,
        name: str = None,
    ):
        super().__init__(name)
        self.lower_price = lower_price
        self.upper_price = upper_price

        self.fee_percent = pool.fee.fraction
        self.gas_cost = gas_cost
        self.swap_fee = pool.fee.fraction

    def rebalance(self, *args, **kwargs) -> str:
        record = kwargs["record"]
        portfolio = kwargs["portfolio"]
        price_before, price = record["price_before"], record["price"]

        is_rebalanced = None

        if len(portfolio.positions) == 0:
            self.create_uni_position(portfolio=portfolio, price=price)
            is_rebalanced = "mint"

        if "UniV3Passive" in portfolio.positions:
            uni_pos: UniV3Position = portfolio.get_position("UniV3Passive")
            # uni_pos.charge_fees(price_before, price)
            uni_pos.charge_fees_share(amount0=record['amount0'], amount1=record['amount1'], liquidity=record['liquidity'])

        return is_rebalanced

    def create_uni_position(self, portfolio, price):
        x = 1 / price
        y = 1

        bi_cur = BiCurrencyPosition(
            name=f"main_vault",
            swap_fee=self.swap_fee,
            gas_cost=self.gas_cost,
            x=x,
            y=y,
            x_interest=None,
            y_interest=None,
        )
        uni_pos = UniV3Position(
            name=f"UniV3Passive",
            lower_price=self.lower_price,
            upper_price=self.upper_price,
            fee_percent=self.fee_percent,
            gas_cost=self.gas_cost,
        )

        portfolio.append(bi_cur)
        portfolio.append(uni_pos)

        dx, dy = uni_pos.aligner.get_amounts_for_swap_to_optimal(
            x, y, swap_fee=bi_cur.swap_fee, price=price
        )

        if dx > 0:
            bi_cur.swap_x_to_y(dx, price=price)
        if dy > 0:
            bi_cur.swap_y_to_x(dy, price=price)

        x_uni, y_uni = uni_pos.aligner.get_amounts_after_optimal_swap(
            x, y, swap_fee=bi_cur.swap_fee, price=price
        )
        bi_cur.withdraw(x_uni, y_uni)
        uni_pos.deposit(x_uni, y_uni, price=price)


class StrategyByAddress(AbstractStrategy):
    """
    ``StrategyByAddress`` is the strategy on UniswapV3 that follows the actions of certain address.

    Attributes:
        address: The address to follow.
        pool: UniswapV3 Pool instance.
        gas_cost: Gas costs, expressed in currency.
        name: Unique name for the instance.
    """

    def __init__(
        self,
        address: str,
        pool: Pool,
        gas_cost: float,
        name: str = None,
    ):
        super().__init__(name)

        self.address = address
        self.decimal_diff = -pool.decimals_diff
        self.fee_percent = pool.fee.fraction
        self.gas_cost = gas_cost

    def rebalance(self, *args, **kwargs):
        is_rebalanced = None

        record = kwargs["record"]
        portfolio = kwargs["portfolio"]
        event = record["event"]

        if event == "mint":
            if record["owner"] == self.address:
                amount_0, amount_1, tick_lower, tick_upper, liquidity = (
                    record["amount0"],
                    record["amount1"],
                    record["tick_lower"],
                    record["tick_upper"],
                    record["liquidity"],
                )
                self.perform_mint(
                    portfolio, amount_0, amount_1, tick_lower, tick_upper, liquidity
                )
                is_rebalanced = "mint"

        if event == "burn":
            if record["owner"] == self.address:
                amount_0, amount_1, tick_lower, tick_upper, liquidity, price = (
                    record["amount0"],
                    record["amount1"],
                    record["tick_lower"],
                    record["tick_upper"],
                    record["liquidity"],
                    record["price"],
                )
                self.perform_burn(
                    portfolio,
                    amount_0,
                    amount_1,
                    tick_lower,
                    tick_upper,
                    liquidity,
                    price,
                )
                is_rebalanced = "burn"

        if event == "swap":
            if record["owner"] == self.address:
                amount_0, amount_1 = record["amount0"], record["amount1"]
                self.perform_swap(portfolio, amount_0, amount_1)
                is_rebalanced = "swap"

        if event == "swap":
            price_before, price = record["price_before"], record["price"]
            for name, pos in portfolio.positions.items():
                if "Uni" in name:
                    pos.charge_fees(price_before, price)

        self.perform_clearing(portfolio)
        return is_rebalanced

    def perform_swap(self, portfolio, amount_0, amount_1):
        vault = portfolio.get_position("Vault")
        if amount_0 > 0:
            if vault.x < amount_0:
                vault.deposit(amount_0 - vault.x + 1e-6, 0)
            vault.withdraw(amount_0, 0)
            vault.deposit(0, -amount_1)
        else:
            if vault.y < amount_1:
                vault.deposit(0, amount_1 - vault.y + 1e-6)
            vault.withdraw(0, amount_1)
            vault.deposit(-amount_0, 0)

    def perform_mint(
        self, portfolio, amount_0, amount_1, tick_lower, tick_upper, liquidity
    ):
        name = f"UniV3_{tick_lower}_{tick_upper}"
        vault = portfolio.get_position("Vault")

        if vault.x < amount_0:
            vault.deposit(amount_0 - vault.x + 1e-6, 0)

        if vault.y < amount_1:
            vault.deposit(0, amount_1 - vault.y + 1e-6)

        x_uni, y_uni = vault.withdraw(amount_0, amount_1)

        price_lower, price_upper = self._tick_to_price(tick_lower), self._tick_to_price(
            tick_upper
        )

        if name in portfolio.positions:
            univ3_pos_old = portfolio.get_position(name)
            univ3_pos_old.liquidity = univ3_pos_old.liquidity + liquidity
            univ3_pos_old.x_hold += amount_0
            univ3_pos_old.y_hold += amount_1
            # univ3_pos_old.bi_currency.deposit(amount_0, amount_1)
        else:
            univ3_pos = UniV3Position(
                name, price_lower, price_upper, self.fee_percent, self.gas_cost
            )
            univ3_pos.liquidity = liquidity
            univ3_pos.x_hold += amount_0
            univ3_pos.y_hold += amount_1
            # univ3_pos.bi_currency.deposit(amount_0, amount_1)
            portfolio.append(univ3_pos)

    def perform_burn(
        self, portfolio, amount_0, amount_1, tick_lower, tick_upper, liquidity, price
    ):
        name = f"UniV3_{tick_lower}_{tick_upper}"

        if name in portfolio.positions:
            univ3_pos_old = portfolio.get_position(name)
            vault = portfolio.get_position("Vault")
            vault.deposit(amount_0, amount_1)

            if liquidity > 0:
                if liquidity > univ3_pos_old.liquidity:
                    print("Diff =", liquidity - univ3_pos_old.liquidity)
                    x_out, y_out = univ3_pos_old.burn(univ3_pos_old.liquidity, price)
                else:
                    x_out, y_out = univ3_pos_old.burn(liquidity, price)
            else:
                print(f"Negative liq {liquidity}")
        else:
            print(f"There is no position to burn {name}")

    def perform_clearing(self, portfolio):
        poses = copy.copy(portfolio.positions)
        for name, pos in poses.items():
            if "UniV3" in name:
                univ3 = portfolio.get_position(name)
                if univ3.liquidity < 1e1:
                    portfolio.remove(name)

    def _tick_to_price(self, tick):
        price = np.power(1.0001, tick)
        return price


class StrategyCatchThePrice(AbstractStrategy):
    """
    ``UniV3Passive`` is the passive strategy on UniswapV3 without rebalances.
        lower_price: Lower bound of the interval
        upper_price: Upper bound of the interval
        rebalance_cost: Rebalancing cost, expressed in currency
        pool: UniswapV3 Pool instance
        name: Unique name for the instance
    """

    def __init__(
        self,
        name: str,
        pool: Pool,
        gas_cost: float,
        width: int,
        seconds_to_hold: int
    ):
        super().__init__(name)
        self.fee_percent = pool.fee.percent
        self.gas_cost = gas_cost
        self.swap_fee = pool.fee.percent

        self.width = width
        self.seconds_to_hold = seconds_to_hold

        self.last_mint_price = None
        self.last_timestamp_in_interval = None
        self.pos_num = None
        self.w = 0
        self.create_pos_time = None

    def create_pos(self, x_in, y_in, price, timestamp, portfolio):
        """
            Swaps x_in, y_in in right proportion and mint to new interval
        """
        if self.pos_num is None:
            self.pos_num = 1
        else:
            self.pos_num += 1

        # bicurrency position that can swap tokens
        bi_cur: BiCurrencyPosition = portfolio.get_position('main_vault')

        # add tokens to bicurrency position
        bi_cur.deposit(x_in, y_in)

        # new uni position
        uni_pos = UniV3Position(
            name=f'UniV3_{self.pos_num}',
            lower_price=max(1.0001 ** MIN_TICK, price - self.width),
            upper_price=min(1.0001 ** MAX_TICK, price + self.width),
            fee_percent=self.fee_percent,
            gas_cost=self.gas_cost,
        )

        # add new position to portfolio
        portfolio.append(uni_pos)

        # uni_pos.aligner is UniswapLiquidityAligner, good class for working with liquidity operations
        dx, dy = uni_pos.aligner.get_amounts_for_swap_to_optimal(
            x_in, y_in, swap_fee=bi_cur.swap_fee, price=price
        )

        # swap tokens to right proportion (if price in interval swaps to equal liquidity in each token)
        if dx > 0:
            bi_cur.swap_x_to_y(dx, price=price)
        if dy > 0:
            bi_cur.swap_y_to_x(dy, price=price)

        x_uni, y_uni = uni_pos.aligner.get_amounts_after_optimal_swap(
            x_in, y_in, swap_fee=bi_cur.swap_fee, price=price
        )
        assert (x_uni, y_uni == bi_cur.to_xy(price))
        uni_pos.aligner.check_xy_is_optimal(price, x_uni, y_uni)

        # withdraw tokens from bicurrency
        # because of float numbers precision subtract 1e-9
        bi_cur.withdraw(x_uni, y_uni)

        # deposit tokens to uni
        uni_pos.deposit(x_uni, y_uni, price=price)

        # remember last mint price to track price in interval
        self.last_mint_price = price

        # remember timestamp price was in interval
        self.last_timestamp_in_interval = timestamp
        self.create_pos_time = timestamp

        print("created", uni_pos.fees_x)

    def rebalance(self, *args, **kwargs) -> str:
        """
            Function of AbstractStrategy
            In Backtest.backtest this function process every row of historic data

            Return: name of portfolio action, that will be processed by RebalanceViewer
        """
        # record is row of historic data
        record = kwargs['record']
        timestamp = record['timestamp']
        event = record['event']

        # portfolio managed by the strategy
        portfolio = kwargs['portfolio']
        price_before, price = record['price_before'], record['price']

        # process only swap events
        if event != 'swap':
            return None

        if len(portfolio.positions) == 0:
            # create biccurency positions for swap
            bi_cur = BiCurrencyPosition(
                name=f'main_vault',
                swap_fee=self.swap_fee,
                gas_cost=self.gas_cost,
                x=0,
                y=0,
                x_interest=None,
                y_interest=None
            )
            portfolio.append(bi_cur)

            # create first uni interval
            self.create_pos(x_in=1/price, y_in=1, price=price, timestamp=timestamp, portfolio=portfolio)
            return 'init'

        # collect fees from uni
        uni_pos = portfolio.get_position(f'UniV3_{self.pos_num}')
        # uni_pos.charge_fees(price_0=price_before, price_1=price)
        uni_pos.charge_fees_share(amount0=record['amount0'], amount1=record['amount1'],
                                  liquidity=record['liquidity'], price_0=price_before, price_1=price, tick=record["tick"])

        # if price in interval update last_timestamp_in_interval
        if abs(self.last_mint_price - price) < self.width:
            self.last_timestamp_in_interval = timestamp
            return None

        # if price outside interval for long create new uni position
        if (timestamp - self.last_timestamp_in_interval).total_seconds() > self.seconds_to_hold:
            if (self.w < 5):
                self.w += 1
                uni_pos: UniV3Position = portfolio.get_position(f'UniV3_{self.pos_num}')
                x_out, y_out = uni_pos.withdraw(price)
                print("Time:", (timestamp - self.create_pos_time))

                portfolio.remove(f'UniV3_{self.pos_num}')

                self.create_pos(x_in=x_out, y_in=y_out, price=price, timestamp=timestamp, portfolio=portfolio)
                return 'rebalance'

        return None
