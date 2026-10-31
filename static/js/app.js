document.addEventListener('DOMContentLoaded', () => {
  const body = document.body;
  const menuToggle = document.querySelector('#menu-toggle');
  const closeMenu = () => {
    body.classList.remove('menu-open');
    menuToggle?.setAttribute('aria-expanded', 'false');
  };

  menuToggle?.addEventListener('click', () => {
    const open = body.classList.toggle('menu-open');
    menuToggle.setAttribute('aria-expanded', String(open));
  });
  document.querySelector('[data-menu-close]')?.addEventListener('click', closeMenu);
  document.querySelectorAll('.side-nav a').forEach((link) => link.addEventListener('click', closeMenu));

  document.querySelectorAll('.flash-close').forEach((button) => {
    button.addEventListener('click', () => button.closest('.flash')?.remove());
  });

  document.querySelectorAll('[data-password-toggle]').forEach((button) => {
    button.addEventListener('click', () => {
      const input = document.getElementById(button.dataset.passwordToggle);
      if (!input) return;
      const reveal = input.type === 'password';
      input.type = reveal ? 'text' : 'password';
      button.textContent = reveal ? 'Hide' : 'Show';
      button.setAttribute('aria-label', reveal ? 'Hide password' : 'Show password');
    });
  });

  const loanForm = document.querySelector('#loan-form');
  if (loanForm) {
    const principalInput = loanForm.querySelector('#principal');
    const monthlyOutput = loanForm.querySelector('#monthly-estimate');
    const rolloverOutput = loanForm.querySelector('#rollover-estimate');
    const eligibility = loanForm.querySelector('#eligibility-message');
    const submit = loanForm.querySelector('#loan-submit');
    const max = Number(loanForm.dataset.limit);
    const rate = Number(loanForm.dataset.rate) / 100;
    const formatKsh = (value) => `KSh ${value.toLocaleString('en-KE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

    const updateEstimate = () => {
      const principal = Number(principalInput.value);
      const valid = Number.isFinite(principal) && principal > 0 && principal <= max;
      const settlement = valid ? principal * (1 + rate) : 0;
      const rollover = valid ? principal * (rate + 0.5) : 0;
      monthlyOutput.textContent = formatKsh(settlement);
      rolloverOutput.textContent = `Rollover minimum (interest + 50% principal): ${formatKsh(rollover)}`;
      eligibility.classList.toggle('is-valid', valid);
      eligibility.classList.toggle('is-invalid', principal > max);
      submit.disabled = !valid;
      if (principal > max) {
        eligibility.textContent = `Over your available limit of ${formatKsh(max)}. Reduce the requested amount to continue.`;
      } else if (principal > 0 && valid) {
        eligibility.textContent = `Within your ${formatKsh(max)} limit. Full settlement in 30 days: ${formatKsh(settlement)}.`;
      } else if (max <= 0) {
        eligibility.textContent = 'No borrowing capacity is currently available.';
      } else {
        eligibility.textContent = `Available borrowing capacity: ${formatKsh(max)}.`;
      }
    };
    principalInput.addEventListener('input', updateEstimate);
    updateEstimate();
  }

  const search = document.querySelector('#member-search');
  const memberRows = [...document.querySelectorAll('.member-table-row')];
  const registryEmpty = document.querySelector('#registry-empty');
  search?.addEventListener('input', () => {
    const query = search.value.trim().toLowerCase();
    let visible = 0;
    memberRows.forEach((row) => {
      const match = row.dataset.search.includes(query);
      row.hidden = !match;
      if (match) visible += 1;
    });
    if (registryEmpty) registryEmpty.hidden = visible > 0;
  });

  const drawer = document.querySelector('#member-drawer');
  const drawerContent = document.querySelector('#member-detail-content');
  const closeDrawer = () => {
    body.classList.remove('drawer-open');
    drawer?.setAttribute('aria-hidden', 'true');
    memberRows.forEach((row) => row.classList.remove('selected'));
  };
  document.querySelector('#drawer-close')?.addEventListener('click', closeDrawer);
  document.querySelector('#detail-scrim')?.addEventListener('click', closeDrawer);

  const money = (value) => `KSh ${Number(value || 0).toLocaleString('en-KE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const make = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const addSection = (title, entries, getParts) => {
    const section = make('section', 'drawer-section');
    section.append(make('h3', '', title));
    if (!entries.length) {
      section.append(make('div', 'drawer-placeholder', 'No records yet.'));
    } else {
      entries.forEach((entry) => {
        const row = make('div', 'drawer-item');
        getParts(entry).forEach((part) => row.append(part));
        section.append(row);
      });
    }
    drawerContent.append(section);
  };

  memberRows.forEach((row) => {
    row.addEventListener('click', async () => {
      memberRows.forEach((item) => item.classList.toggle('selected', item === row));
      body.classList.add('drawer-open');
      drawer?.setAttribute('aria-hidden', 'false');
      drawerContent.replaceChildren(make('div', 'drawer-placeholder', 'Loading member history…'));
      try {
        const response = await fetch(`/staff/members/${row.dataset.memberId}`, { headers: { Accept: 'application/json' } });
        if (!response.ok) throw new Error('Member details could not be loaded.');
        const data = await response.json();
        drawerContent.replaceChildren();
        const profile = make('div', 'detail-profile');
        profile.append(make('span', 'avatar', data.member.full_name.slice(0, 1).toUpperCase()));
        const identity = make('div');
        identity.append(make('strong', '', data.member.full_name));
        identity.append(make('span', '', `MW-${String(data.member.id).padStart(4, '0')} · ${data.member.email}`));
        profile.append(identity);
        drawerContent.append(profile);

        const metrics = make('div', 'detail-metrics');
        [
          ['LOCKED SAVINGS', money(data.financials.savings)],
          ['ACTIVE BALANCE', money(data.financials.active_balance)],
          ['3× LIMIT', money(data.financials.limit)],
          ['AVAILABLE', money(data.financials.remaining)],
        ].forEach(([label, value]) => {
          const item = make('div', 'detail-metric');
          item.append(make('span', '', label), make('strong', '', value));
          metrics.append(item);
        });
        drawerContent.append(metrics);
        addSection('Savings history', data.savings, (entry) => [
          make('span', '', new Date(entry.date.replace(' ', 'T')).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })),
          make('strong', '', money(entry.amount)),
        ]);
        addSection('Loan history', data.loans, (entry) => {
          const detail = make('span');
          detail.append(make('strong', '', `Loan #${entry.id} · ${money(entry.principal_amount)}`));
          detail.append(make('span', '', `${money(entry.balance_due)} balance · ${new Date(entry.applied_date.replace(' ', 'T')).toLocaleDateString('en-GB')}`));
          const badge = make('span', `badge badge-${entry.status}`, entry.status.replace('_', ' '));
          return [detail, badge];
        });
      } catch (error) {
        drawerContent.replaceChildren(make('div', 'drawer-placeholder', error.message));
      }
    });
  });
});