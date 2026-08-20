/* RAISR-SME scoring engine -- a port of score_vector() from
   analysis/instrument_validation.py, the engine that produced the paper's numbers. Pure logic,
   no DOM and no dependencies: instrument/test_scoring.py loads this in Node and checks it
   digit-for-digit against instrument/scoring.py, which is in turn checked against the original.

   Two details are load-bearing for that parity and must not be "tidied":

   1. Summation order. Dimension scores are summed in the bank's own key order, and each
      dimension's items in their bank order, because the Python engine does and floating-point
      addition is not associative. Iterating display_order instead would silently drift.
   2. Sequential accumulation. numpy's pairwise summation reduces to a plain sequential loop below
      eight elements, and no dimension holds more than six items, so a plain loop matches it.

   Loaded by a bare <script> tag, never as an ES module: under file:// the module path is blocked
   by the same opaque-origin rule that blocks fetch(). */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) { module.exports = factory(); }
  else { root.RAISR = factory(); }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var ANSWERS = ['yes', 'no', 'dk'];

  /* Risk coding. Gap items score risk when a control is ABSENT; exposure items (A1-A4, V1) score
     risk when the exposure is PRESENT. A single global Yes=0 mapping inverts the AI dimension --
     the defect corrected at the v1 freeze, recorded in freeze_record.fixes_at_freeze. */
  function riskOf(answer, riskWhen) {
    if (answer === 'dk' || answer === null || answer === undefined) { return 0.5; }
    if (riskWhen === 'yes') { return answer === 'yes' ? 1 : 0; }
    return answer === 'no' ? 1 : 0;
  }

  function eachItem(bank, fn) {
    var keys = Object.keys(bank.dimensions);
    for (var i = 0; i < keys.length; i++) {
      var items = bank.dimensions[keys[i]].items;
      for (var j = 0; j < items.length; j++) { fn(items[j], keys[i]); }
    }
  }

  /* Display order for anything a person reads; bank order for anything that gets summed. */
  function itemsInDisplayOrder(bank) {
    var out = [];
    bank.display_order.forEach(function (key) {
      bank.dimensions[key].items.forEach(function (item) {
        out.push({ item: item, dimension: key });
      });
    });
    return out;
  }

  function answersToRisks(answers, bank) {
    var risks = {};
    eachItem(bank, function (item) {
      risks[item.id] = riskOf(answers[item.id], item.risk_when);
    });
    return risks;
  }

  /* Bands are half-open [lo, hi), so a score sitting exactly on a cut point belongs to the band
     above. That makes the last bit of a float decisive, and it is not a hypothetical: across
     50,000 random response vectors, 83 total to exactly 40, 65 or 85 -- about one respondent in
     600. Accumulated left to right, a vector whose exact total is 40 can land at
     39.999999999999996 and be shown "Low" where the instrument defines "Medium".

     Quantising to nine decimals first removes that class of error. Nine is chosen to sit far
     below any difference a person could act on and far above the ~1e-14 accumulation noise;
     instrument/test_scoring.py measures both ends of that gap. */
  function quantize(x) { return Math.round(x * 1e9) / 1e9; }

  function bandFor(total, bands) {
    var t = quantize(total);
    var keys = Object.keys(bands);
    for (var i = 0; i < keys.length; i++) {
      var lo = bands[keys[i]][0], hi = bands[keys[i]][1];
      if (t >= lo && t < hi) { return keys[i]; }
    }
    return keys[keys.length - 1];
  }

  /* Port of score_vector(). Input is risk-coded (0 / 0.5 / 1) per item id, as the Python engine
     consumes; use answersToRisks() to get there from yes/no/dk. */
  function scoreVector(risks, bank) {
    var dimensions = {};
    var keys = Object.keys(bank.dimensions);
    var i, j;

    for (i = 0; i < keys.length; i++) {
      var items = bank.dimensions[keys[i]].items;
      var sum = 0;
      for (j = 0; j < items.length; j++) {
        var v = risks[items[j].id];
        if (typeof v !== 'number' || v !== v) {
          throw new Error('no risk value for item ' + items[j].id);
        }
        sum += v;
      }
      dimensions[keys[i]] = (sum / items.length) * 100;
    }

    var total = 0;
    var dimKeys = Object.keys(dimensions);
    for (i = 0; i < dimKeys.length; i++) {
      total += dimensions[dimKeys[i]] * bank.weights[dimKeys[i]];
    }

    return { total: total, band: bandFor(total, bank.bands), dimensions: dimensions };
  }

  /* Ranked remediation list.

     WEBSITE DESIGN DECISION, NOT A RESULT FROM THE PAPER. The paper promises a "prioritised action
     list" and instrument_validation.py checks only that every (dimension x band) pair HAS an
     action -- it defines no order. Ranking by weighted contribution (dimension score x weight)
     reads "largest gap" as largest contribution to the total, so the item that moves the score
     most is fixed first. Ties break by weight, then by display order, so the output is
     deterministic. Any UI showing this list must state that the ordering is its own choice. */
  function rankedActions(dimensions, bank) {
    var rows = bank.display_order.map(function (key, index) {
      var score = dimensions[key];
      var weight = bank.weights[key];
      var band = bandFor(score, bank.bands);
      return {
        dimension: key,
        label: bank.dimensions[key].label,
        score: score,
        weight: weight,
        contribution: score * weight,
        band: band,
        action: bank.action_plans[key][band],
        criterion_status: bank.dimensions[key].criterion_status,
        order: index
      };
    });
    rows.sort(function (a, b) {
      return (b.contribution - a.contribution) || (b.weight - a.weight) || (a.order - b.order);
    });
    return rows;
  }

  function dontKnowItems(answers, bank) {
    var out = [];
    eachItem(bank, function (item) { if (answers[item.id] === 'dk') { out.push(item.id); } });
    return out;
  }

  /* Share links. 25 trits pack five-to-a-byte (3^5 = 243 < 256) into 5 bytes, so a full response
     set is ~7 base64url characters. It rides on the URL fragment, which browsers never transmit --
     a shared profile therefore reaches no server, which is the whole point. */
  var B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';

  function encodeAnswers(answers, bank) {
    var order = itemsInDisplayOrder(bank);
    var trits = order.map(function (row) {
      var a = answers[row.item.id];
      return a === 'yes' ? 1 : (a === 'no' ? 2 : 0);
    });
    var bytes = [], i, k, acc;
    for (i = 0; i < trits.length; i += 5) {
      acc = 0;
      for (k = 4; k >= 0; k--) { acc = acc * 3 + (trits[i + k] || 0); }
      bytes.push(acc);
    }
    var bits = 0, buf = 0, out = '';
    for (i = 0; i < bytes.length; i++) {
      buf = (buf << 8) | bytes[i]; bits += 8;
      while (bits >= 6) { bits -= 6; out += B64[(buf >> bits) & 63]; }
    }
    if (bits > 0) { out += B64[(buf << (6 - bits)) & 63]; }
    return 'A' + out;
  }

  function decodeAnswers(code, bank) {
    if (!code || code[0] !== 'A') { return null; }
    var body = code.slice(1), buf = 0, bits = 0, bytes = [], i;
    for (i = 0; i < body.length; i++) {
      var idx = B64.indexOf(body[i]);
      if (idx < 0) { return null; }
      buf = (buf << 6) | idx; bits += 6;
      if (bits >= 8) { bits -= 8; bytes.push((buf >> bits) & 255); }
    }
    var order = itemsInDisplayOrder(bank);
    var need = Math.ceil(order.length / 5);
    if (bytes.length < need) { return null; }
    var trits = [];
    for (i = 0; i < need; i++) {
      var acc = bytes[i];
      for (var k = 0; k < 5; k++) { trits.push(acc % 3); acc = Math.floor(acc / 3); }
    }
    var answers = {};
    order.forEach(function (row, n) {
      answers[row.item.id] = trits[n] === 1 ? 'yes' : (trits[n] === 2 ? 'no' : 'dk');
    });
    return answers;
  }

  return {
    ANSWERS: ANSWERS,
    riskOf: riskOf,
    answersToRisks: answersToRisks,
    scoreVector: scoreVector,
    bandFor: bandFor,
    quantize: quantize,
    rankedActions: rankedActions,
    dontKnowItems: dontKnowItems,
    itemsInDisplayOrder: itemsInDisplayOrder,
    encodeAnswers: encodeAnswers,
    decodeAnswers: decodeAnswers
  };
}));
