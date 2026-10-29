
(function(){
  var MK_KEY = 'ii_market_v2';

  // ---------- 市场筛选 ----------
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
      });
    });
  }

  // ---------- 打字机（40 字/秒，连续点击跳过） ----------
  var typer = {timer:null, full:'', el:null};
  function typeText(el, text){
    clearInterval(typer.timer);
    el.textContent = '';
    var i = 0, caret = document.createElement('span');
    caret.className = 'caret'; caret.textContent = '\u25BC';
    el.appendChild(caret);
    typer.el = el; typer.full = text;
    typer.timer = setInterval(function(){
      if (i >= text.length){
        clearInterval(typer.timer);
        return;
      }
      i++;
      el.textContent = text.slice(0, i);
      el.appendChild(caret);
    }, 25);   // 25ms ≈ 40 字/秒
  }
  function skipType(){
    if (!typer.el) return false;
    clearInterval(typer.timer);
    typer.el.textContent = typer.full;
    var caret = document.createElement('span');
    caret.className = 'caret'; caret.textContent = '\u25BC';
    typer.el.appendChild(caret);
    typer.el.scrollTop = 0;
    return true;
  }

  // ---------- 抽屉 ----------
  var mask, drawer, DATA_MAP = {};
  if(window.__DATA){ window.__DATA.forEach(function(d){ DATA_MAP[d.i] = d; }); }

  function openDrawer(id){
    if(!drawer) return;
    var src = document.getElementById('d-' + id);
    var html = src ? src.innerHTML : (DATA_MAP[id] || {}).h;
    if(!html) return;
    drawer.innerHTML = html +
      '<button class="close" aria-label="关闭" onclick="window.__closeDrawer()">X</button>';
    drawer.classList.add('on');
    if(mask) mask.classList.add('on');
    document.body.style.overflow = 'hidden';
    drawer.scrollTop = 0;
    // 摘要打字机
    var sum = drawer.querySelector('.sum');
    if(sum){
      var full = sum.getAttribute('data-text') || sum.textContent;
      typeText(sum, full);
    }
  }
  window.__openDrawer = function(id){
    if (skipType()) return;   // 已开着的先跳过动画
    openDrawer(id);
  };
  window.__closeDrawer = function(){
    clearInterval(typer.timer);
    if(!drawer) return;
    drawer.classList.remove('on');
    if(mask) mask.classList.remove('on');
    document.body.style.overflow = '';
  };
  if(mask) mask.addEventListener('click', window.__closeDrawer);
  document.addEventListener('keydown', function(e){
    if(e.key === 'Escape') window.__closeDrawer();
  });

  // ---------- 检索 ----------
  function initSearch(){
    var box = document.getElementById('q');
    if(!box || !window.__DATA) return;
    var data = window.__DATA, list = document.getElementById('results');
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
      }).slice(0, 120);

      cnt.textContent = '> ' + rows.length + ' HITS' + (rows.length >= 120 ? ' (TOP 120)' : '');
      if(!rows.length){
        list.innerHTML = '<div class="empty"><b>NO MATCH</b>换个关键词或放宽筛选条件</div>';
        return;
      }
      list.innerHTML = rows.map(function(d){
        var lv = d.l === 'critical' ? 'critical' : d.l === 'important' ? 'important' : '';
        var t = d.y === 'opinion' ? '<span class="badge opinion">观点</span>' : '';
        var c = d.c && d.c < 0.65 ? '<span class="badge lowconf">低置信</span>' : '';
        return '<div class="item"><div class="score ' + lv + '">' + (d.v || '--') +
          '<small>' + d.w + '</small></div><div>' +
          '<div class="i-title" onclick="window.__openDrawer(\'' + d.i + '\')">' + d.t + '</div>' +
          '<div class="i-sum">' + (d.s || '') + '</div>' +
          '<div class="i-meta"><span class="badge">' + d.n + '</span>' + t +
          '<span>' + d.o + '</span>' + c + '</div></div></div>';
      }).join('');
    }
    [box, fTrack, fMarket, fType, fLevel].forEach(function(el){
      if(el) el.addEventListener(el === box ? 'input' : 'change', render);
    });
    render();
  }

  document.addEventListener('DOMContentLoaded', function(){
    mask = document.querySelector('.drawer-mask');
    drawer = document.querySelector('.drawer');
    initMarket(); initSearch();
  });
})();
