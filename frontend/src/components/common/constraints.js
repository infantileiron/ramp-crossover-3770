import { api } from '../../api/client.js';
import { bindForm, notice } from '../../hooks/forms.js';
import { e, sec } from '../../utils/format.js';

function rulePanel(constraints, edit) {
  const rule = constraints.rule;
  const body = edit
    ? `<form id="rule-form" class="constraint-form">
        <div class="form-inline">
          <label>单人下限（秒）<input name="min_seconds" type="number" min="0.01" max="900" step="0.01" required value="${rule ? sec(rule.min_seconds) : '0.01'}"></label>
          <label>单人上限（秒）<input name="max_seconds" type="number" min="0.01" max="900" step="0.01" required value="${rule ? sec(rule.max_seconds) : '900'}"></label>
        </div>
        <p class="form-error" role="alert" hidden></p>
        <button class="secondary" type="submit">保存用时规则</button>
      </form>`
    : `<dl class="constraint-readonly"><div><dt>单人用时范围</dt><dd>${rule ? `${sec(rule.min_seconds)} – ${sec(rule.max_seconds)} 秒` : '未设置（默认 0.01 – 900 秒）'}</dd></div></dl>`;
  return `<section class="panel"><div class="panel-title"><h2>用时规则 · 单人范围</h2>
      <p>对每个缺测格统一生效；已测值不受影响。更新会推进约束代际。</p></div>${body}</section>`;
}

function totalRow(routeCode, period, total, edit) {
  const value = total ? sec(total.total_seconds) : '未补录';
  const form = edit
    ? `<form class="total-form" data-period="${period}">
        <input name="total_seconds" type="number" min="0.01" max="12000" step="0.01" required placeholder="全员总用时（秒）" value="${total ? sec(total.total_seconds) : ''}">
        <button class="text-button" type="submit">保存</button>
        ${total ? `<button class="text-button danger" type="button" data-delete="${period}">清除</button>` : ''}
      </form>`
    : '';
  return `<li><strong>第 ${period} 轮全员总用时</strong><span>${value}</span>${form}</li>`;
}

function totalsPanel(routeCode, constraints, edit) {
  const byPeriod = Object.fromEntries(constraints.totals.map(row => [row.period, row]));
  return `<section class="panel"><div class="panel-title"><h2>每轮全员总用时</h2>
      <p>含该轮已测用时；推演时自动扣除已测合计，仅约束缺测格。可只补一轮。</p></div>
      <ul class="total-list">${[1, 2].map(period => totalRow(routeCode, period, byPeriod[period], edit)).join('')}</ul></section>`;
}

export function constraintsPanel(root, { route, constraints, user, refresh }) {
  const edit = user.role === 'analyst';
  const holder = document.createElement('div');
  holder.className = 'constraint-grid';
  holder.innerHTML = `${rulePanel(constraints, edit)}${totalsPanel(route.code, constraints, edit)}
    <p class="generation-note">当前约束代际 <strong>#${constraints.generation}</strong> ·
      用时规则或总用时更新后，代际 +1；冻结在旧代际的待发布结论将无法发布，已发布报告可照常回看。</p>`;
  root.append(holder);

  if (!edit) return;
  bindForm('rule-form', async values => {
    await api.saveTimingRule(route.code, {
      min_seconds: values.min_seconds, max_seconds: values.max_seconds,
    });
    notice('用时规则已保存，约束代际已推进。');
    await refresh();
  });
  holder.querySelectorAll('.total-form').forEach(form => {
    const period = Number(form.dataset.period);
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const error = form.querySelector('.form-error');
      if (error) error.hidden = true;
      try {
        const data = Object.fromEntries(new FormData(form));
        await api.saveRoundTotal(route.code, period, { total_seconds: data.total_seconds });
        notice(`第 ${period} 轮全员总用时已保存，约束代际已推进。`);
        await refresh();
      } catch (err) {
        if (error) { error.textContent = err.message; error.hidden = false; } else notice(err.message);
      }
    });
    form.querySelector('[data-delete]')?.addEventListener('click', async () => {
      await api.deleteRoundTotal(route.code, period);
      notice(`已清除第 ${period} 轮总用时，约束代际已推进。`);
      await refresh();
    });
  });
}
