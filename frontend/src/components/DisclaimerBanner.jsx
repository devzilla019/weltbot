const ITEMS = [
  "⚠ RISK WARNING: Crypto futures trading involves substantial risk — you may lose your entire capital",
  "💡 WeltBot is an algorithmic tool, not financial advice — always do your own research",
  "🔐 Your API keys are stored locally in your browser and never shared with any server",
  "📉 High leverage amplifies losses as well as gains — use risk management",
  "⚠ This platform is for educational purposes — trade on testnet before using real funds",
  "🤖 Past strategy performance does not guarantee future results",
  "💡 Never invest money you cannot afford to lose — set daily loss limits",
  "⚠ Cryptocurrency markets operate 24/7 and can be highly volatile",
];

export default function DisclaimerBanner() {
  const doubled = [...ITEMS, ...ITEMS];
  return (
    <div className="disclaimer-wrap">
      <div className="disclaimer-inner">
        {doubled.map((item, i) => (
          <span key={i} className="disclaimer-item">
            <span className="disclaimer-icon">{item.split(" ")[0]}</span>
            {item.slice(item.indexOf(" ") + 1)}
            <span style={{ color:"var(--text3)", margin:"0 10px" }}>|</span>
          </span>
        ))}
      </div>
    </div>
  );
}

