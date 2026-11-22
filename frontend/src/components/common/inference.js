import { e, sec } from '../../utils/format.js';

function fillTable(title, rows, sign) {
  if (!rows || !rows.length) return '';
  return `<div class="fill-col"><h4>${title}</h4>
    <table><thead><tr><th>缺测编号</th><th>补录用时（秒）</th></tr></thead>
    <tbody>${rows.map(item => `<tr><th scope="row" class="code">${e(item.code)}</th><td class="number">${sec(item.seconds)}</td></tr>`).join('')}</tbody></table>
    <p class="fill-sign">对应处理差${sign}</p></div>`;
}

export function inferencePanel(result, plan) {
  const inference = result.inference;
  if (!inference) return '';
  if (inference.status === 'no_missing') {
    return `<section class="panel inference"><div class="panel-title"><h2>缺测推演</h2>
      <p>本快照两轮记录齐全，无需补录；处理差点估计直接由完整配对算出。</p></div></section>`;
  }
  if (inference.status === 'infeasible') {
    return `<section class="panel inference has-alert"><div class="panel-title"><h2>缺测推演 · 无解</h2>
      <p>按现场约束不存在可行补法，处理差可达区间无法构造，不能据此试挂。</p></div>
      <ul class="alert-list">${inference.reasons.map(reason => `<li>${e(reason)}</li>`).join('')}</ul>
      <p class="caveat">请核对单人用时范围或该轮全员总用时，或补录真实用时后重新运行。</p></section>`;
  }
  const allNegative = inference.treatment_max < 0;
  return `<section class="panel inference ${allNegative ? 'all-negative' : 'crosses-zero'}">
    <div class="panel-title"><h2>缺测推演 · 处理差可达区间</h2>
      <p>已测值照用，缺测格在单人范围与每轮全员总用时内取可行值，求处理差 τ = (Δ_AB − Δ_BA)/2 的上下界。</p></div>
    <div class="bounds">
      <div><dt>可达下界（最有利于 B）</dt><dd class="metric-value">${sec(inference.treatment_min, true)} <small>秒</small></dd></div>
      <div><dt>可达上界（最不利于 B）</dt><dd class="metric-value">${sec(inference.treatment_max, true)} <small>秒</small></dd></div>
    </div>
    <p class="bounds-verdict"><span class="status ${allNegative ? 'ok' : 'warn'}">${allNegative ? '区间整体在零以下' : '区间触及或越过零'}</span>
      ${allNegative ? '保留原门槛且其余条件满足时，允许安排局部试挂。' : '无法保证补全后 B 仍较短，不允许试挂。'}</p>
    <div class="fill-grid">
      ${fillTable('下界对应补法', inference.fills.min, '取最小值')}
      ${fillTable('上界对应补法', inference.fills.max, '取最大值')}
    </div>
    <p class="caveat">约束：单人 ${sec(inference.rule_min)} – ${sec(inference.rule_max)} 秒；
      第 1 轮总用时 ${inference.totals[1] != null ? sec(inference.totals[1]) + ' 秒' : '未约束'}；
      第 2 轮总用时 ${inference.totals[2] != null ? sec(inference.totals[2]) + ' 秒' : '未约束'}。
      缺测格：${e(inference.missing_cells.join('、'))}。</p>
  </section>`;
}

export function staleBanner(report) {
  if (!report.stale) return '';
  return `<div class="stale-banner" role="alert">现场用时规则或总用时已更新（当前代际 #${report.current_generation}，
    本报告冻结于 #${report.frozen_generation}）。该结论已过期，${report.state === 'published' ? '仅作存档回看。' : '不可发布，请基于新台账重新运行。'}</div>`;
}
