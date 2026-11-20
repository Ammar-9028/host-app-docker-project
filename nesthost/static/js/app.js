(function () {
  'use strict';
  var $ = function (s) { return document.querySelector(s); };
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }

  // reveal on scroll
  var io = 'IntersectionObserver' in window ? new IntersectionObserver(function (es) { es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } }); }, { threshold: .12 }) : null;
  document.querySelectorAll('.rv').forEach(function (el) { io ? io.observe(el) : el.classList.add('in'); });

  // domain / subdomain checker (home page + domain guide)
  function checker(form, input, out) {
    if (!form) return;
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var v = input.value.trim().toLowerCase();
      if (!v) return;
      out.className = out.className.replace(/\b(ok|bad)\b/g, '').trim(); out.textContent = 'Check ho raha hai...';
      var full = v.indexOf('.') > -1;
      fetch(full ? '/api/domain?d=' + encodeURIComponent(v) : '/api/check?name=' + encodeURIComponent(v))
        .then(function (r) { return r.json(); }).then(function (j) {
          if (j.error) { out.className += ' bad'; out.textContent = j.error; return; }
          if (full) {
            var m = { taken: ['bad', esc(j.domain) + ' pehle se registered hai.'], available: ['ok', esc(j.domain) + ' shayad available hai. Kisi registrar par confirm karo (paid hota hai).'], unknown: ['bad', 'Abhi is domain ka status nahi mil paya.'] }[j.status];
            out.className += ' ' + m[0]; out.innerHTML = m[1] + (j.status === 'available' ? ' Ya <a href="/signup">free subdomain lo</a>.' : '');
          } else if (j.available) {
            out.className += ' ok'; out.innerHTML = esc(j.host) + ' available hai! <a href="/signup?next=/dashboard">Free mein claim karo</a>';
          } else { out.className += ' bad'; out.textContent = j.reason || 'Available nahi hai.'; }
        }).catch(function () { out.className += ' bad'; out.textContent = 'Check nahi ho paya. Dobara try karo.'; });
    });
  }
  checker($('#dc'), $('#dcq'), $('#dcr'));
  checker($('#dc2'), $('#dc2q'), $('#dc2r'));

  // live subdomain hint on dashboard
  var sub = $('#sub'), hint = $('#subh'), t;
  if (sub) sub.addEventListener('input', function () {
    clearTimeout(t); var v = sub.value.trim().toLowerCase(); hint.className = 'hint'; if (!v) { hint.textContent = ''; return; }
    t = setTimeout(function () { fetch('/api/check?name=' + encodeURIComponent(v)).then(function (r) { return r.json(); }).then(function (j) { hint.className = 'hint ' + (j.available ? 'ok' : 'bad'); hint.textContent = j.available ? 'Available' : (j.reason || ''); }).catch(function () { }); }, 350);
  });

  // zip upload with progress
  var zf = $('#zipform');
  if (zf) {
    var drop = $('#zdrop'), file = zf.querySelector('input[type=file]'), bar = zf.querySelector('.bar2'), msg = $('#zmsg');
    drop.addEventListener('click', function () { file.click(); });
    drop.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); file.click(); } });
    ['dragenter', 'dragover'].forEach(function (ev) { drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add('over'); }); });
    ['dragleave', 'drop'].forEach(function (ev) { drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove('over'); }); });
    drop.addEventListener('drop', function (e) { if (e.dataTransfer.files[0]) send(e.dataTransfer.files[0]); });
    file.addEventListener('change', function () { if (file.files[0]) send(file.files[0]); });
    function send(f) {
      var fd = new FormData(); fd.append('csrf', zf.querySelector('[name=csrf]').value); fd.append('zip', f);
      bar.hidden = false; bar.firstElementChild.style.width = '0'; msg.className = 'hint'; msg.textContent = 'Upload ho raha hai...';
      var x = new XMLHttpRequest(); x.open('POST', zf.dataset.action);
      x.upload.onprogress = function (e) { if (e.lengthComputable) bar.firstElementChild.style.width = Math.round(e.loaded / e.total * 100) + '%'; };
      x.onload = function () {
        var j = {}; try { j = JSON.parse(x.responseText); } catch (e) { }
        msg.className = 'hint ' + (j.ok ? 'ok' : 'bad'); msg.textContent = j.message || 'Upload fail hua.';
        if (j.ok) setTimeout(function () { location.reload(); }, 1200);
      };
      x.onerror = function () { msg.className = 'hint bad'; msg.textContent = 'Connection toot gaya.'; };
      x.send(fd);
    }
  }

  document.querySelectorAll('[data-copy]').forEach(function (b) {
    b.addEventListener('click', function () { var old = b.textContent; (navigator.clipboard ? navigator.clipboard.writeText(b.dataset.copy) : Promise.reject()).then(function () { b.textContent = 'Copy ho gaya'; }).catch(function () { b.textContent = b.dataset.copy; }); setTimeout(function () { b.textContent = old; }, 2000); });
  });
})();
