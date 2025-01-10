from mellow_sdk.primitives import Pool, POOLS
from mellow_sdk.data import RawDataUniV3
from mellow_sdk.strategies import UniV3Passive
from mellow_sdk.backtest import Backtest
from mellow_sdk.viewers import RebalanceViewer, UniswapViewer, PortfolioViewer
from mellow_sdk.positions import BiCurrencyPosition, UniV3Position

pool_num = 4
pool = Pool(
    tokenA=POOLS[pool_num]['token0'],
    tokenB=POOLS[pool_num]['token1'],
    fee=POOLS[pool_num]['fee']
)

data = RawDataUniV3(pool, 'data', reload_data=False).load_from_folder()

univ3_passive = UniV3Passive(
    lower_price=data.swaps['price'].min() * 0.9,
    upper_price=data.swaps['price'].max() * 1.1,
    pool=pool,
    gas_cost=0.,
    name='passive'
)

bt = Backtest(strategy=univ3_passive)
portfolio_history, rebalance_history, uni_history = bt.backtest(df=data.swaps)

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
rebalances_plot.show()
fig1.show()
fig2.show()
fig3.show()
fig4.show()
fig5.show()
fig6.show()
stats.tail(2)
