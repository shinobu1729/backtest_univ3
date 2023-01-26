from mellow_sdk.primitives import Pool, POOLS
from mellow_sdk.data import RawDataUniV3
from mellow_sdk.strategies import AbstractStrategy, UniV3Passive, StrategyCatchThePrice
from mellow_sdk.backtest import Backtest
from mellow_sdk.viewers import RebalanceViewer, UniswapViewer, PortfolioViewer
from mellow_sdk.positions import BiCurrencyPosition, UniV3Position


pool_num = 1
pool = Pool(
    tokenA=POOLS[pool_num]['token0'],
    tokenB=POOLS[pool_num]['token1'],
    fee=POOLS[pool_num]['fee']
)

# if there is no folder or files, create and download
data = RawDataUniV3(pool=pool, data_dir='data', reload_data=False).load_from_folder()

catch_strat = StrategyCatchThePrice(
    name='name',
    pool=pool,
    gas_cost=0,  # in this strategy gas can eat all portfolio, for this example set 0
    width=0.5,
    seconds_to_hold=60*60
)

bt = Backtest(strategy=catch_strat)
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


# number of rebalances
rv.rebalance_history.to_df().shape[0]

rebalances_plot.show()
intervals_plot.show()
rebalances_plot.write_image('catch_rebalances.png')
