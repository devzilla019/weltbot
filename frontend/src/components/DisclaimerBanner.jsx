const ITEMS=["⚠ RISK WARNING: Crypto futures trading involves substantial risk — you may lose your entire capital","💡 WeltBot is an algorithmic tool, not financial advice — always do your own research","🔐 Your API keys are encrypted and stored securely — never shared with third parties","📉 High leverage amplifies losses as well as gains — always use proper risk management","⚠ Never invest money you cannot afford to lose — set daily loss limits","🤖 Past strategy performance does not guarantee future results","💡 Always test on testnet before switching to mainnet with real funds"];
export default function DisclaimerBanner(){
  const doubled=[...ITEMS,...ITEMS];
  return(
    <div className="disclaimer-wrap">
      <div className="disclaimer-inner">{doubled.map((item,i)=><span key={i} className="disclaimer-item">{item}<span style={{color:"var(--text3)",margin:"0 16px"}}>|</span></span>)}</div>
    </div>
  );
}
