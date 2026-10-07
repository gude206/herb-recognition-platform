import { AncientBookDecoration, BotanicalDecoration } from './DashboardDecorations'

export function DashboardHero() {
  return <section className="dashboard-hero" aria-labelledby="dashboard-title">
    <div className="dashboard-hero-art" aria-hidden="true"><AncientBookDecoration/><BotanicalDecoration/><span className="hero-vertical">本草绵延<br/>智识传承</span></div>
    <div className="dashboard-hero-inner"><div className="dashboard-hero-copy">
      <div className="dashboard-hero-eyebrow"><span/>数据资源 · 模型表现</div>
      <div className="dashboard-title-line"><h1 id="dashboard-title">数据看板</h1><span className="dashboard-seal">本草<br/>数据</span></div>
      <h2>可视化展示中草药数据资源、图像数据集统计与模型识别性能</h2>
      <p>基于丰富的中草药图像与知识数据，呈现资源分布、模型效果与使用情况，<br className="desktop-break"/>助力中草药文化的数字化传承与智能应用。</p>
    </div></div>
  </section>
}
