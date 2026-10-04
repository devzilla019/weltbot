import { useState, useEffect } from 'react';
import CRTSignalCard from './CRTSignalCard';
import { forexApi } from '../api';
import '../index.css';

function ForexTab() {
  const [forexData, setForexData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchForexData();
    const interval = setInterval(fetchForexData, 10000);
    return () => clearInterval(interval);
  }, []);

  const fetchForexData = async () => {
    try {
      const data = await forexApi.getStatus();
      setForexData(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="text-gray-400">Loading forex data...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-900/20 border border-red-500 rounded-lg p-4">
        <p className="text-red-400">Error: {error}</p>
      </div>
    );
  }

  if (!forexData || !forexData.enabled) {
    return (
      <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-8 text-center">
        <h3 className="text-xl text-gray-400 mb-2">Forex Trading Disabled</h3>
        <p className="text-gray-500">Set FOREX_ENABLED=true to activate forex trading</p>
      </div>
    );
  }

  const { biases, crt_levels, positions, kronos_available } = forexData;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-gradient-to-r from-blue-900/30 to-purple-900/30 border border-blue-800/50 rounded-lg p-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-white mb-1">Forex & Metals Trading</h2>
            <p className="text-gray-400">CRT + SMC + Kronos AI Strategy</p>
          </div>
          <div className="text-right">
            <div className={`text-sm font-semibold ${
              kronos_available ? 'text-green-400' : 'text-red-400'
            }`}>
              Kronos AI: {kronos_available ? 'ACTIVE' : 'OFFLINE'}
            </div>
            <div className="text-xs text-gray-500 mt-1">
              3-Layer System: Bias → CRT → SMC
            </div>
          </div>
        </div>
      </div>

      {/* Position Summary */}
      {positions && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
            <div className="text-gray-400 text-sm mb-1">Open Positions</div>
            <div className="text-2xl font-bold text-white">{positions.open_count}</div>
          </div>
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
            <div className="text-gray-400 text-sm mb-1">Total P&L</div>
            <div className={`text-2xl font-bold ${
              positions.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'
            }`}>
              ${positions.total_pnl?.toFixed(2)}
            </div>
          </div>
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
            <div className="text-gray-400 text-sm mb-1">Win Rate</div>
            <div className="text-2xl font-bold text-blue-400">{positions.win_rate}%</div>
          </div>
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
            <div className="text-gray-400 text-sm mb-1">Closed Trades</div>
            <div className="text-2xl font-bold text-white">
              <span className="text-green-400">{positions.wins}</span>
              <span className="text-gray-500 mx-1">/</span>
              <span className="text-red-400">{positions.losses}</span>
            </div>
          </div>
        </div>
      )}

      {/* Open Positions */}
      {positions?.open_positions?.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-lg font-semibold text-white">Open Positions</h3>
          {positions.open_positions.map((pos) => (
            <div
              key={pos.id}
              className="bg-gray-800/80 border border-gray-700 rounded-lg p-4"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-4">
                  <div className={`px-3 py-1 rounded text-sm font-bold ${
                    pos.signal === 'BUY'
                      ? 'bg-green-500/20 text-green-400'
                      : 'bg-red-500/20 text-red-400'
                  }`}>
                    {pos.signal}
                  </div>
                  <div>
                    <div className="text-white font-semibold text-lg">{pos.symbol}</div>
                    <div className="text-gray-400 text-sm">
                      {pos.lots} lots • {pos.confidence}% conf
                    </div>
                  </div>
                </div>
                <div className="text-right">
                  <div className={`text-xl font-bold ${
                    pos.pnl >= 0 ? 'text-green-400' : 'text-red-400'
                  }`}>
                    ${pos.pnl?.toFixed(2)}
                  </div>
                  <div className="text-sm text-gray-400">
                    Entry: {pos.entry?.toFixed(5)}
                  </div>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="text-gray-500">Current:</span>
                  <span className="text-white ml-2">{pos.current?.toFixed(5)}</span>
                </div>
                <div>
                  <span className="text-gray-500">SL:</span>
                  <span className="text-red-400 ml-2">{pos.sl?.toFixed(5)}</span>
                </div>
                <div>
                  <span className="text-gray-500">TP:</span>
                  <span className="text-green-400 ml-2">{pos.tp?.toFixed(5)}</span>
                </div>
              </div>
              <div className="mt-2 flex items-center space-x-2 text-xs">
                <span className="px-2 py-1 bg-blue-500/20 text-blue-400 rounded">
                  {pos.kronos_bias}
                </span>
                <span className="px-2 py-1 bg-purple-500/20 text-purple-400 rounded">
                  CRT: {pos.crt_setup}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Pair Signals */}
      <div>
        <h3 className="text-lg font-semibold text-white mb-3">Market Signals</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {forexData.pairs?.map((symbol) => {
            const bias = biases?.[symbol];
            const levels = crt_levels?.[symbol];
            return (
              <CRTSignalCard
                key={symbol}
                symbol={symbol}
                bias={bias}
                levels={levels}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default ForexTab;
