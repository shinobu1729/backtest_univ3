from mellow_sdk.primitives import Pool, Token, Fee
from mellow_sdk.data import RawDataUniV3
from mellow_sdk.strategies import UniV3Passive
from mellow_sdk.backtest import Backtest
from mellow_sdk.viewers import RebalanceViewer, UniswapViewer, PortfolioViewer

pool = Pool(Token.WBTC, Token.WETH, Fee.MIDDLE)

data = RawDataUniV3(pool, 'data', reload_data=False).load_from_folder()

univ3_passive = UniV3Passive(
    lower_price=data.swaps['price'].min() - 1,
    upper_price=data.swaps['price'].max() + 1,
    pool=pool,
    gas_cost=0.,
    name='passive'
)

bt = Backtest(univ3_passive)
portfolio_history, rebalance_history, uni_history = bt.backtest(data.swaps)

rv = RebalanceViewer(rebalance_history)
uv = UniswapViewer(uni_history)
pv = PortfolioViewer(portfolio_history, pool)

# Draw portfolio stats, like value, fees earned, apy
fig1, fig2, fig3, fig4, fig5, fig6 = pv.draw_portfolio()

# Draw Uniswap intervals
intervals_plot = uv.draw_intervals(data.swaps)

# Draw rebalances
rebalances_plot = rv.draw_rebalances(data.swaps)

# Calculate df with portfolio stats
stats = portfolio_history.calculate_stats()

intervals_plot.show()