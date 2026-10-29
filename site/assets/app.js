
(function(){
  // ---------- 市场筛选（跨页持久化） ----------
  var MK_KEY = 'ii_market';
  function applyMarket(m){
    document.querySelectorAll('[data-market]').forEach(function(el){
      var mk = el.getAttribute('data-market');
      el.style.display = (m === 'ALL' || mk === m || mk === '') ? '' : 'none';
    });
    document.querySelectorAll('.market-filter button').forEach(function(b){
      b.classList.toggle('on', b.getAttribute('data-m') === m);
    });
  }
  function initMarket(){
    var saved = localStorage.getItem(MK_KEY) || 'ALL';
    applyMarket(saved);
    document.querySelectorAll('.market-filter button').forEach(function(b){
      b.addEventListener('click', function(){
        var m = b.getAttribute('data-m');
        localStorage.setItem(MK_KEY, m);
        applyMarket(m);
        if (window.__recount) window.__recount();
      });
    });
  }

  // ---------- 抽屉 ----------
  var mask = document.querySelector('.drawer-mask');
  var drawer = document.querySelector('.drawer');
  var DATA_MAP = {};
  if(window.__DATA){ window.__DATA.forEach(function(d){ DATA_MAP[d.i] = d; }); }
  function openDrawer(id){
    if(!drawer) return;
    var src = document.getElementById('d-' + id);
    var html = src ? src.innerHTML : (DATA_MAP[id] || {}).h;
    if(!html) return;
    drawer.innerHTML = html +
      '<button class="close" aria-label="关闭" onclick="window.__closeDrawer()">&times;</button>';
    drawer.classList.add('on');
    if(mask) mask.classList.add('on');
    document.body.style.overflow = 'hidden';
  }
  window.__openDrawer = openDrawer;
  window.__closeDrawer = function(){
    if(!drawer) return;
    drawer.classList.remove('on');
    if(mask) mask.classList.remove('on');
    document.body.style.overflow = '';
  };
  if(mask) mask.addEventListener('click', window.__closeDrawer);
  document.addEventListener('keydown', function(e){
    if(e.key === 'Escape') window.__closeDrawer();
  });

  // ---------- 看板时间范围切换 ----------
  window.__range = function(n){
    document.querySelectorAll('[data-range]').forEach(function(el){
      el.style.display = el.getAttribute('data-range') === String(n) ? '' : 'none';
    });
    document.querySelectorAll('.range-btn').forEach(function(b){
      b.classList.toggle('on', b.getAttribute('data-r') === String(n));
    });
  };
  function initRange(){
    if(!document.querySelector('[data-range]')) return;
    document.querySelectorAll('.range-btn').forEach(function(b){
      b.addEventListener('click', function(){ window.__range(b.getAttribute('data-r')); });
    });
  }

  // ---------- 检索 ----------
  function initSearch(){
    var box = document.getElementById('q');
    if(!box || !window.__DATA) return;
    var data = window.__DATA;
    var list = document.getElementById('results');
    var cnt = document.getElementById('rcount');
    var fTrack = document.getElementById('f-track');
    var fMarket = document.getElementById('f-market');
    var fType = document.getElementById('f-type');
    var fLevel = document.getElementById('f-level');

    function render(){
      var q = box.value.trim().toLowerCase();
      var rows = data.filter(function(d){
        if(q && (d.t + ' ' + d.s).toLowerCase().indexOf(q) === -1) return false;
        if(fTrack && fTrack.value && d.k !== fTrack.value) return false;
        if(fMarket && fMarket.value && d.m !== fMarket.value) return false;
        if(fType && fType.value && d.y !== fType.value) return false;
        if(fLevel && fLevel.value && d.l !== fLevel.value) return false;
        return true;
      }).slice(0, 200);

      cnt.textContent = '命中 ' + rows.length + ' 条' + (rows.length >= 200 ? '（仅显示前 200）' : '');
      if(!rows.length){
        list.innerHTML = '<div class="empty"><b>没有匹配的条目</b>试试换关键词，或放宽时间与筛选条件</div>';
        return;
      }
      list.innerHTML = rows.map(function(d){
        var lv = d.l === 'critical' ? 'critical' : d.l === 'important' ? 'important' : '';
        var badgeType = d.y === 'opinion' ? '<span class="badge opinion">观点</span>' : '';
        var badgeConf = d.c && d.c < 0.65 ? '<span class="badge lowconf">低置信归类</span>' : '';
        return '<div class="item"><div class="score ' + lv + '">' + (d.v || '—') +
          '<small>' + d.w + '</small></div><div>' +
          '<div class="i-title" onclick="window.__openDrawer(\'' + d.i + '\')">' + d.t + '</div>' +
          '<div class="i-sum">' + (d.s || '') + '</div>' +
          '<div class="i-meta"><span class="badge">' + d.n + '</span>' + badgeType +
          '<span>' + d.o + '</span>' + badgeConf + '</div></div></div>';
      }).join('');
    }
    [box, fTrack, fMarket, fType, fLevel].forEach(function(el){
      if(el) el.addEventListener(el === box ? 'input' : 'change', render);
    });
    render();
  }

  document.addEventListener('DOMContentLoaded', function(){
    initMarket(); initRange(); initSearch();
  });
})();
