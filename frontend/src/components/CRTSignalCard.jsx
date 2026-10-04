import { useState, useEffect } from 'react';
import { forexApi } from '../api';
import '../index.css';

function CRTSignalCard({ symbol, bias, levels }) {
  const [price, setPrice] = useState(null);
  const [details, setDetails] = useState(null);

  useEffect(() => {
    fetchDetails();
    const interval = setInterval(fetchDetails, 15000);
    return () => clearInterval(interval);
  }, [symbol]);

  const fetchDetails = async () => {
    try {
      const data = await forexApi.getPair(symbol);
      setPrice(data.current_price);
      setDetails(data);
    } catch (err) {
      console.error(`Failed to fetch ${symbol} details:`, err);
    }
  };

  const getBiasBadge = () => {
    if (!bias) return { color: 'gray', text: 'NEUTRAL' };
    
    const biasValue = bias.bias || 'NEUTRAL';
    if (biasValue === 'BULLISH') return { color: 'green', text: 'BULLISH' };
    if (biasValue === 'BEARISH') return { color: 'red', text: 'BEARISH' };
    return { color: 'gray', text: 'NEUTRAL' };
  };

  const getCRTStatus = () => {
    if (details?.open_trade) {
      return { color: 'blue', text: 'IN TRADE' };
    }
    return { color: 'yellow', text: 'WAITING' };
  };

  const biasBadge = getBiasBadge();
  const crtStatus = getCRTStatus();

  const formatPrice = (val) => {
    if (!val) return '-';
    return parseFloat(val).toFixed(5);
  };

  const calculateRange = () => {
    if (!levels?.pdh || !levels?.pdl) return null;
    const range = levels.pdh - levels.pdl;
    return range.toFixed(5);
  };

  const getPricePosition = () => {
    if (!price || !levels?.pdh || !levels?.pdl) return 50;
    const range = levels.pdh - levels.pdl;
    const position = ((price - levels.pdl) / range) * 100;
    return Math.max(0, Math.min(100, position));
  };

  return (
    <div className="bg-gray-800/80 border border-gray-700 rounded-lg p-4 hover:border-gray-600 transition-all">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-bold text-white">{symbol}</h3>
        <div className={`px-2 py-1 rounded text-xs font-bold ${
          biasBadge.color === 'green'
            ? 'bg-green-500/20 text-green-400'
            : biasBadge.color === 'red'
            ? 'bg-red-500/20 text-red-400'
            : 'bg-gray-500/20 text-gray-400'
        }`}>
          {biasBadge.text}
        </div>
      </div>

      {/* Current Price */}
      <div className="mb-3">
        <div className="text-gray-400 text-xs mb-1">Current Price</div>
        <div className="text-2xl font-bold text-white">
          {price ? formatPrice(price) : '-'}
        </div>
      </div>

      {/* PDH/PDL Levels */}
      {levels && (
        <div className="space-y-2 mb-3">
          <div className="flex justify-between items-center">
            <span className="text-gray-400 text-xs">PDH</span>
            <span className="text-red-400 font-mono text-sm">{formatPrice(levels.pdh)}</span>
          </div>
          
          {/* Price Position Bar */}
          <div className="relative h-2 bg-gray-700 rounded">
            <div
              className="absolute h-full bg-gradient-to-r from-green-500 to-red-500 rounded"
              style={{ width: '100%' }}
            />
            <div
              className="absolute w-1 h-4 bg-white rounded -top-1 transform -translate-x-1/2"
              style={{ left: `${getPricePosition()}%` }}
            />
          </div>
          
          <div className="flex justify-between items-center">
            <span className="text-gray-400 text-xs">PDL</span>
            <span className="text-green-400 font-mono text-sm">{formatPrice(levels.pdl)}</span>
          </div>
          
          <div className="text-center text-gray-500 text-xs">
            Range: {calculateRange()} pips
          </div>
        </div>
      )}

      {/* CRT Status */}
      <div className="flex items-center justify-between pt-3 border-t border-gray-700">
        <span className="text-gray-400 text-xs">CRT Status</span>
        <div className={`px-2 py-1 rounded text-xs font-semibold ${
          crtStatus.color === 'blue'
            ? 'bg-blue-500/20 text-blue-400'
            : 'bg-yellow-500/20 text-yellow-400'
        }`}>
          {crtStatus.text}
        </div>
      </div>

      {/* Kronos Prediction */}
      {bias && bias.predicted_change_pct !== undefined && (
        <div className="mt-2 text-xs text-gray-400">
          <span>Forecast: </span>
          <span className={bias.predicted_change_pct > 0 ? 'text-green-400' : 'text-red-400'}>
            {bias.predicted_change_pct > 0 ? '+' : ''}{bias.predicted_change_pct?.toFixed(2)}%
          </span>
        </div>
      )}

      {/* Recent Performance */}
      {details && details.recent_trades_count > 0 && (
        <div className="mt-2 pt-2 border-t border-gray-700 text-xs">
          <div className="flex justify-between text-gray-400">
            <span>Recent:</span>
            <span>
              <span className="text-green-400">{details.recent_wins}W</span>
              <span className="text-gray-500 mx-1">/</span>
              <span className="text-red-400">{details.recent_losses}L</span>
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

export default CRTSignalCard;
