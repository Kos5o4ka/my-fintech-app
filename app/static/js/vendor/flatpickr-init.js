(function () {
  if (typeof flatpickr === 'undefined') return;

  flatpickr.localize(flatpickr.l10ns.ru);

  var arrows = {
    prevArrow: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="15 18 9 12 15 6"/></svg>',
    nextArrow: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="9 18 15 12 9 6"/></svg>'
  };

  var defaultOpts = {
    dateFormat: 'Y-m-d',
    altInput: true,
    altFormat: 'j F Y',
    disableMobile: true,
    animate: true,
    monthSelectorType: 'dropdown',
    prevArrow: arrows.prevArrow,
    nextArrow: arrows.nextArrow,
    onChange: function (dates, dateStr, inst) {
      var el = inst.input;
      if (el.onchange) el.onchange();
      el.dispatchEvent(new Event('change', { bubbles: true }));
    }
  };

  var timeOpts = {
    enableTime: true,
    noCalendar: true,
    dateFormat: 'H:i',
    altInput: true,
    altFormat: 'H:i',
    disableMobile: true,
    time_24hr: true,
    minuteIncrement: 15,
    prevArrow: arrows.prevArrow,
    nextArrow: arrows.nextArrow
  };

  function init() {
    document.querySelectorAll('input[type="date"]:not([data-fp-done])').forEach(function (el) {
      el.setAttribute('data-fp-done', '1');
      el.type = 'text';
      var opts = Object.assign({}, defaultOpts);
      if (el.value) opts.defaultDate = el.value;
      var fp = flatpickr(el, opts);
      if (el.id) window['_fp_' + el.id] = fp;
    });
    document.querySelectorAll('input[type="time"]:not([data-fp-done])').forEach(function (el) {
      el.setAttribute('data-fp-done', '1');
      el.type = 'text';
      var opts = Object.assign({}, timeOpts);
      if (el.value) opts.defaultDate = el.value;
      var fp = flatpickr(el, opts);
      if (el.id) window['_fp_' + el.id] = fp;
    });
  }

  window.fpSet = function (id, value) {
    var fp = window['_fp_' + id];
    if (fp) { fp.setDate(value, false); }
    else {
      var el = document.getElementById(id);
      if (el) el.value = value;
    }
  };

  window.fpClear = function (id) {
    var fp = window['_fp_' + id];
    if (fp) { fp.clear(); }
    else {
      var el = document.getElementById(id);
      if (el) el.value = '';
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  var observer = new MutationObserver(function () { init(); });
  observer.observe(document.body, { childList: true, subtree: true });
})();
