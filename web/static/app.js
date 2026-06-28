const fmt = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });

  let allTrades = []; // Globally store trades for the modal

  // ── Chart Setup ─────────────────────────────────────────
  let myChart = null;
  function initChart() {
    const ctx = document.getElementById('chart').getContext('2d');
    
    // Dynamic gradient fill
    const grad = ctx.createLinearGradient(0, 0, 0, 350);
    grad.addColorStop(0,   'rgba(14, 165, 233, 0.5)');
    grad.addColorStop(0.5, 'rgba(14, 165, 233, 0.1)');
    grad.addColorStop(1,   'rgba(14, 165, 233, 0.0)');

    myChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [{
          label: 'Portfolio Value',
          data: [],
          borderColor: '#0ea5e9',
          backgroundColor: grad,
          borderWidth: 3,
          pointBackgroundColor: '#050810',
          pointBorderColor: '#0ea5e9',
          pointBorderWidth: 2,
          pointRadius: 4,
          pointHoverRadius: 8,
          pointHoverBackgroundColor: '#0ea5e9',
          pointHoverBorderColor: '#fff',
          fill: true,
          tension: 0.4 // Smooth curves
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(16, 22, 38, 0.95)',
            titleColor: '#94a3b8',
            titleFont: { size: 13, family: 'Outfit' },
            bodyColor: '#f8fafc',
            bodyFont: { size: 16, weight: 'bold', family: 'Outfit' },
            borderColor: 'rgba(255,255,255,0.1)',
            borderWidth: 1,
            padding: 14,
            displayColors: false,
            cornerRadius: 12,
            callbacks: { label: c => fmt.format(c.raw) }
          }
        },
        scales: {
          x: { 
            grid: { color: 'rgba(255,255,255,0.03)', drawBorder: false }, 
            ticks: { color: '#94a3b8', font: { family: 'Outfit' }, maxTicksLimit: 7 } 
          },
          y: { 
            grid: { color: 'rgba(255,255,255,0.05)', borderDash: [5, 5], drawBorder: false }, 
            ticks: { color: '#94a3b8', font: { family: 'Outfit' }, callback: v => '$' + v.toLocaleString() } 
          }
        },
        interaction: { intersect: false, mode: 'index' }
      }
    });
  }

  // ── Fetch & Render ──────────────────────────────────────
  let lastTradesJson = "[]";

  async function fetchAll() {
    try {
      const [statsR, tradesR, histR] = await Promise.all([
        fetch('/api/portfolio'),
        fetch('/api/trades'),
        fetch('/api/portfolio_history')
      ]);
      const stats  = await statsR.json();
      const trades = await tradesR.json();
      const hist   = await histR.json();
      allTrades    = trades; // Store for modal

      // Stats Update
      const change  = stats.balance - stats.start_balance;
      const pct     = ((change / stats.start_balance) * 100).toFixed(2);
      const sign    = change >= 0 ? '+' : '';
      const colour  = change >= 0 ? 'up' : 'down';

      document.getElementById('s-balance').textContent  = fmt.format(stats.balance);
      document.getElementById('s-balance').className    = 'stat-value ' + colour;
      document.getElementById('s-change').textContent   = `${sign}${fmt.format(change)} (${sign}${pct}%)`;
      document.getElementById('s-change').className     = 'stat-sub ' + colour;
      
      document.getElementById('s-trades').textContent   = stats.total_trades;
      document.getElementById('s-win').textContent      = stats.win_rate + '%';

      const pnlEl = document.getElementById('s-pnl');
      pnlEl.textContent = (stats.pnl >= 0 ? '+' : '') + fmt.format(stats.pnl);
      pnlEl.className   = 'stat-value ' + (stats.pnl >= 0 ? 'up' : 'down');

      // Table Update (only re-render if data actually changed to preserve hover states)
      const currentTradesJson = JSON.stringify(trades);
      if (currentTradesJson !== lastTradesJson) {
        lastTradesJson = currentTradesJson;
        const tbody = document.getElementById('tbl-body');
        
        if (!trades.length) {
          tbody.innerHTML = '<tr><td colspan="6" class="empty-note">No active positions. Agent will place trades shortly.</td></tr>';
        } else {
          // Sort by ID descending to put newest on top
          const sorted = trades.sort((a,b) => b.id - a.id);
          tbody.innerHTML = sorted.map(t => {
            const time = new Date(t.placed_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            const action = t.action === 'BUY_YES' ? 'BUY YES' : t.action === 'BUY_NO' ? 'BUY NO' : 'SKIP';
            const acls   = t.action === 'BUY_YES' ? 'b-yes' : t.action === 'BUY_NO' ? 'b-no' : 'b-skip';
            const oc     = t.outcome || 'PENDING';
            const ocls   = oc === 'WON' ? 'b-won' : oc === 'LOST' ? 'b-lost' : 'b-pending';
            const edge   = t.edge ? (t.edge > 0 ? `+${t.edge}%` : `${t.edge}%`) : '–';
            const edgecl = t.edge > 0 ? 'up' : t.edge < 0 ? 'down' : '';
            return `<tr onclick="openModal(${t.id})" style="cursor:pointer" title="Click to view AI reasoning">
              <td style="color:var(--muted); font-size:0.85rem">${time}</td>
              <td style="font-weight:600; color:white">${t.city}</td>
              <td><span class="badge ${acls}">${action}</span></td>
              <td style="font-variant-numeric:tabular-nums; color:white; font-weight:500">${fmt.format(t.bet_size_usd || 0)}</td>
              <td class="${edgecl}" style="font-weight:700">${edge}</td>
              <td><span class="badge ${ocls}">${oc}</span></td>
            </tr>`;
          }).join('');
          
          // Re-apply filter if active
          filterTrades();
        }
      }

      // Chart Update
      if (hist.length && myChart) {
        let labels = hist.map(h => {
          const d = new Date(h.recorded_at);
          return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        });
        let data = hist.map(h => h.balance);
        
        // Always add starting point
        if (data.length > 0 && data[0] !== stats.start_balance) { 
          labels.unshift('Start'); 
          data.unshift(stats.start_balance); 
        }
        
        myChart.data.labels = labels;
        myChart.data.datasets[0].data = data;
        myChart.update(); // Enabled smooth Chart.js animations
      }

      // Hide Initial Loader
      const loader = document.getElementById('loader');
      if (loader) { 
        loader.style.opacity = '0'; 
        setTimeout(() => loader.remove(), 600); 
      }

    } catch (err) {
      console.error('Dashboard sync error:', err);
    }
  }

  // ── Modal Handlers ──────────────────────────────────────
  let activeFilterMode = '';
  
  function setFilterBtn(btnEl, mode) {
    // Remove active class from all
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    // Add to clicked
    btnEl.classList.add('active');
    
    activeFilterMode = mode.toLowerCase();
    filterTrades();
  }

  function filterTrades() {
    const input = document.getElementById('trade-filter');
    if (!input) return;
    const query = input.value.toLowerCase();
    const tbody = document.getElementById('tbl-body');
    const rows = tbody.querySelectorAll('tr:not(#empty-filter-msg)');
    
    let visibleCount = 0;
    
    rows.forEach(row => {
      // Don't filter empty note row if it's the global empty note
      if (row.classList.contains('empty-note')) return; 
      
      const text = row.innerText.toLowerCase();
      
      // First check mode filter (won/lost/pending)
      let matchesMode = true;
      if (activeFilterMode) {
         const statusCell = row.cells[5] ? row.cells[5].innerText.toLowerCase() : '';
         if (statusCell !== activeFilterMode) matchesMode = false;
      }
      
      // Then check text query
      const matchesText = text.includes(query);
      
      const isVisible = matchesMode && matchesText;
      row.style.display = isVisible ? '' : 'none';
      
      if (isVisible) visibleCount++;
    });
    
    // Handle the "No trades found" message
    let emptyMsgRow = document.getElementById('empty-filter-msg');
    
    if (visibleCount === 0 && rows.length > 0) {
      if (!emptyMsgRow) {
        emptyMsgRow = document.createElement('tr');
        emptyMsgRow.id = 'empty-filter-msg';
        emptyMsgRow.innerHTML = '<td colspan="6" class="empty-note">No trades found matching your filters.</td>';
        tbody.appendChild(emptyMsgRow);
      }
      emptyMsgRow.style.display = '';
    } else if (emptyMsgRow) {
      emptyMsgRow.style.display = 'none';
    }
  }

  function openModal(tradeId) {
    const t = allTrades.find(x => x.id === tradeId);
    if (!t) return;
    
    document.getElementById('m-title').innerHTML = `Trade on ${t.city}`;
    document.getElementById('m-question').textContent = t.question || t.city;
    document.getElementById('m-time').textContent = new Date(t.placed_at).toLocaleString();
    
    document.getElementById('m-our-prob').textContent = `${t.our_probability}%`;
    document.getElementById('m-mkt-prob').textContent = `${t.market_price}%`;
    
    const edgeText = t.edge > 0 ? `+${t.edge}%` : `${t.edge}%`;
    document.getElementById('m-edge').textContent = edgeText;
    document.getElementById('m-edge').className = t.edge > 0 ? 'up' : 'down';
    
    document.getElementById('m-kelly').textContent = `${(t.kelly_fraction*100).toFixed(1)}%`;
    
    const acls = t.action === 'BUY_YES' ? 'b-yes' : t.action === 'BUY_NO' ? 'b-no' : 'b-skip';
    document.getElementById('m-action').innerHTML = `<span class="badge ${acls}">${t.action.replace('_',' ')}</span>`;
    document.getElementById('m-bet').textContent = fmt.format(t.bet_size_usd || 0);
    
    document.getElementById('m-reason').textContent = t.reason || "No reason provided by LLM.";
    
    document.getElementById('tradeModal').classList.add('active');
  }

  function closeModal(e) {
    if (e) e.preventDefault();
    document.getElementById('tradeModal').classList.remove('active');
  }

  // ── Agent Control Logic ─────────────────────────────────
  let countdownInterval = null;
  let currentSecondsLeft = 0;

  async function fetchAgentStatus() {
    try {
      const res = await fetch('/api/agent/status');
      const data = await res.json();
      currentSecondsLeft = data.seconds_until_next || 0;
      updateAgentUI(data.running, data.working);
    } catch (err) {
      console.error('Status fetch error:', err);
    }
  }

  function formatTime(sec) {
    const m = Math.floor(sec / 60).toString().padStart(2, '0');
    const s = (sec % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  }

  function startLocalTimer() {
    if (countdownInterval) clearInterval(countdownInterval);
    countdownInterval = setInterval(() => {
      if (currentSecondsLeft > 0) {
        currentSecondsLeft--;
        document.getElementById('timer-text').textContent = formatTime(currentSecondsLeft);
      }
    }, 1000);
  }

  function updateAgentUI(isRunning, isWorking) {
    const btn = document.getElementById('btn-toggle');
    const dot = document.getElementById('agent-dot');
    const txt = document.getElementById('agent-text');
    const timerWrap = document.getElementById('agent-timer');
    const timerTxt = document.getElementById('timer-text');

    if (isRunning) {
      btn.classList.add('running');
      txt.textContent = 'AGENT ACTIVE';
      
      if (isWorking) {
        dot.className = 'dot dot-working';
        txt.textContent = 'EXECUTING CYCLE...';
        timerWrap.style.display = 'none';
      } else {
        dot.className = 'dot dot-on';
        timerWrap.style.display = 'block';
        timerTxt.textContent = formatTime(currentSecondsLeft);
      }
    } else {
      btn.classList.remove('running');
      txt.textContent = 'START AGENT';
      timerWrap.style.display = 'none';
      
      if (isWorking) {
        dot.className = 'dot dot-working';
        txt.textContent = 'EXECUTING CYCLE...';
      } else {
        dot.className = 'dot dot-off';
      }
    }
  }

  async function toggleAgent() {
    try {
      // Optimistic update
      const btn = document.getElementById('btn-toggle');
      const isCurrentlyRunning = btn.classList.contains('running');
      
      if (!isCurrentlyRunning) {
        document.getElementById('agent-dot').className = 'dot dot-working';
        document.getElementById('agent-text').textContent = 'STARTING...';
      }
      
      await fetch('/api/agent/toggle', { method: 'POST' });
      
      // Wait a tiny bit for the python backend thread to wake up from its 2s idle sleep
      setTimeout(fetchAgentStatus, 500);
      setTimeout(fetchAgentStatus, 2000);
    } catch (err) {
      console.error('Toggle error:', err);
    }
  }

  async function forceRun() {
    try {
      // Optimistic UI update
      document.getElementById('agent-dot').className = 'dot dot-working';
      document.getElementById('agent-text').textContent = 'EXECUTING CYCLE...';
      
      await fetch('/api/agent/force_run', { method: 'POST' });
      
      // Once complete, refresh everything
      setTimeout(() => {
        fetchAll();
        fetchAgentStatus();
      }, 1000);
    } catch (err) {
      console.error('Force run error:', err);
      fetchAgentStatus();
    }
  }

  initChart();
  fetchAll();
  fetchAgentStatus();
  startLocalTimer();
  setInterval(fetchAll, 1000); // Super fast auto-refresh (1s) to match Telegram
  setInterval(fetchAgentStatus, 1000); // Check agent status frequently (1s)