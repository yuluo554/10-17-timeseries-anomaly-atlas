/*
 * zaa_mirror.js -- hand-written JavaScript mirror of the anomaly-atlas kernel (M3, K4/K13).
 *
 * It is a *translation*, not an optimisation: every function below corresponds statement for
 * statement to a Python function, and each carries a `mirrors:` line naming its counterpart, so
 * a change on one side is visibly a change on the other (plan/02 3.1). The arithmetic stays
 * inside IEEE-754 double + - * / and floor/ceil/abs/min/max, because these are the operations
 * that are bit-identical across CPython and V8; a transcendental or a library reduction would
 * differ by an ulp and the recomputation could then fail at random (plan/02 3.2). The mirror is
 * inside the lexical scope of tests/test_no_transcendental.py, which scans it for exactly that.
 *
 * What it does NOT do: it never re-estimates the period. run.json carries the effective
 * `period_points` and every resolved parameter, and the mirror consumes those values (K8/D13).
 * Re-running the estimator here would put "estimator implementation differences" into the
 * fingerprint, which is the one thing the effective-value contract exists to prevent.
 *
 * What it also does not do: parse timestamps. The inlined rows are already integer epoch
 * milliseconds, so time parsing (and its timezone database) never enters the recomputation (K5).
 *
 * mirrors: anomaly_atlas.canon    (quantize / fixed_to_str / canonical_json_text / sha256_hex)
 * mirrors: anomaly_atlas.timebase (epoch_ms_to_iso)
 * mirrors: anomaly_atlas.detect   (rolling_mad_z / rolling_iqr / stl_resid_z / rules /
 *                                  grid_positions / dominant_interval)
 * mirrors: anomaly_atlas.episodes (merge_episodes / order_episodes / assign_ids / severity_key)
 *
 * Public surface (used by the browser boot script and by tools/mirror_parity.py's Node harness):
 *   ZAA.utf8Bytes(text)  -> number[]           UTF-8 bytes, hand-written (no TextEncoder needed)
 *   ZAA.sha256Hex(bytes) -> string             self-contained SHA-256 (the Web Crypto digest is
 *                                              not used: its secure-context behaviour over the
 *                                              local-file scheme is not consistent across
 *                                              browsers, and it would be "calling a library"
 *                                              rather than a mirror)
 *   ZAA.canonicalJsonText(value) -> string
 *   ZAA.fixedToStr(q, decimals) -> string
 *   ZAA.quantize(x, decimals) -> number
 *   ZAA.recompute(payload) -> {canonical, digest, points}
 *   ZAA.verdict(result, expected, tamper) -> report object (VERIFIED / MISMATCH + first difference)
 */

var ZAA = (function () {
  "use strict";

  /* Directory of the effective constants. `MAD_TO_SIGMA` and the decimal-resolution fraction are
   * the same numbers detect.py declares; a divergence here is a divergence in the verdict. */
  var MAD_TO_SIGMA = 1.4826;
  var DECIMAL_RESOLUTION_FRACTION = 0.000001;
  var RULE_NAMES = ["static_threshold", "pct_jump", "missing_run", "zero_run", "cusum"];

  /* ==========================================================================================
   * Fixed point: the only way a decimal reaches the hash (mirrors canon)
   * ========================================================================================== */

  /* mirrors: canon._power_of_ten -- powers are expanded into repeated multiplication, because
   * the exponent operator is implementation-defined for our purposes and is banned on this path. */
  function powerOfTen(decimals) {
    var scale = 1;
    for (var step = 0; step < decimals; step = step + 1) {
      scale = scale * 10;
    }
    return scale;
  }

  /* mirrors: canon.quantize -- half-to-even, expressed in integer arithmetic after the one float
   * multiplication, so no language-provided float formatting takes part. */
  function quantize(x, decimals) {
    var scale = powerOfTen(decimals);
    var scaled = x * scale;
    var floored = Math.floor(scaled);
    var frac = scaled - floored;
    if (frac > 0.5) {
      return floored + 1;
    }
    if (frac < 0.5) {
      return floored;
    }
    return (floored % 2) ? floored + 1 : floored;
  }

  /* mirrors: canon.fixed_to_str -- the decimal display string is built from the scaled integer,
   * never by asking the platform to format the float. */
  function fixedToStr(q, decimals) {
    var value = Math.trunc(q);
    var digits = Math.trunc(decimals);
    var sign = value < 0 ? "-" : "";
    var magnitude = Math.abs(value);
    if (digits === 0) {
      return sign + String(magnitude);
    }
    var scale = powerOfTen(digits);
    return sign + String(Math.floor(magnitude / scale)) + "." + zeroPad(magnitude % scale, digits);
  }

  function zeroPad(value, width) {
    var text = String(value);
    while (text.length < width) {
      text = "0" + text;
    }
    return text;
  }

  /* ==========================================================================================
   * Canonical JSON (mirrors canon.canonical_json_text)
   * ========================================================================================== */

  /* Code-point order, which is what Python's string comparison does. A plain default sort would
   * compare UTF-16 code units; the two differ only for astral characters, so they are not
   * interchangeable in principle -- and "the key order is part of the bytes" is the whole point. */
  function codePointCompare(left, right) {
    if (left === right) {
      return 0;
    }
    var i = 0;
    var j = 0;
    while (i < left.length && j < right.length) {
      var a = left.codePointAt(i);
      var b = right.codePointAt(j);
      if (a !== b) {
        return a < b ? -1 : 1;
      }
      i = i + (a > 0xffff ? 2 : 1);
      j = j + (b > 0xffff ? 2 : 1);
    }
    if (i < left.length) {
      return 1;
    }
    if (j < right.length) {
      return -1;
    }
    return 0;
  }

  /* mirrors: json.dumps(ensure_ascii=False) string escaping: quote, backslash and the control
   * characters, and nothing else (a `/` and a non-ASCII character stay literal). */
  function jsonString(text) {
    var out = "\"";
    for (var i = 0; i < text.length; i = i + 1) {
      var ch = text.charAt(i);
      var code = text.charCodeAt(i);
      if (ch === "\"") {
        out = out + "\\\"";
      } else if (ch === "\\") {
        out = out + "\\\\";
      } else if (ch === "\n") {
        out = out + "\\n";
      } else if (ch === "\r") {
        out = out + "\\r";
      } else if (ch === "\t") {
        out = out + "\\t";
      } else if (ch === "\b") {
        out = out + "\\b";
      } else if (ch === "\f") {
        out = out + "\\f";
      } else if (code < 32) {
        out = out + "\\u" + ("000" + code.toString(16)).slice(-4);
      } else {
        out = out + ch;
      }
    }
    return out + "\"";
  }

  /* mirrors: the "canonical JSON carries no float literal" rule. An integer-valued number is
   * rendered as plain digits; anything else is a defect and is reported instead of serialised. */
  function jsonNumber(value) {
    if (value !== value || value === Infinity || value === -Infinity) {
      throw new Error("canonical JSON cannot carry a non-finite number");
    }
    if (Math.floor(value) !== value) {
      throw new Error("canonical JSON forbids a float literal: " + String(value));
    }
    if (value === 0) {
      return "0";
    }
    if (Math.abs(value) >= 1000000000000000000000) {
      throw new Error("canonical JSON number is outside the plainly printable integer range");
    }
    return String(value);
  }

  function dumpJson(value, indent) {
    if (value === null) {
      return "null";
    }
    if (typeof value === "string") {
      return jsonString(value);
    }
    if (typeof value === "boolean") {
      return value ? "true" : "false";
    }
    if (typeof value === "number") {
      return jsonNumber(value);
    }
    if (Array.isArray(value)) {
      return dumpArray(value, indent);
    }
    return dumpObject(value, indent);
  }

  /* mirrors: json.dumps(indent=2) layout: one element per line, `,` + newline between them, the
   * closing bracket on its own line at the parent's indent, and empty containers inline. */
  function dumpArray(items, indent) {
    if (items.length === 0) {
      return "[]";
    }
    var inner = indent + "  ";
    var parts = [];
    for (var i = 0; i < items.length; i = i + 1) {
      parts.push(inner + dumpJson(items[i], inner));
    }
    return "[\n" + parts.join(",\n") + "\n" + indent + "]";
  }

  function dumpObject(value, indent) {
    var keys = Object.keys(value).sort(codePointCompare);
    if (keys.length === 0) {
      return "{}";
    }
    var inner = indent + "  ";
    var parts = [];
    for (var i = 0; i < keys.length; i = i + 1) {
      parts.push(inner + jsonString(keys[i]) + ": " + dumpJson(value[keys[i]], inner));
    }
    return "{\n" + parts.join(",\n") + "\n" + indent + "}";
  }

  /* mirrors: canon.canonical_json_text -- sorted keys, no ASCII escaping, 2-space indent, LF. */
  function canonicalJsonText(value) {
    return dumpJson(value, "") + "\n";
  }

  /* ==========================================================================================
   * UTF-8 + SHA-256 (hand-written; the hash input is the UTF-8 byte sequence of the text)
   * ========================================================================================== */

  function utf8Bytes(text) {
    var bytes = [];
    var i = 0;
    while (i < text.length) {
      var code = text.charCodeAt(i);
      if (code < 0x80) {
        bytes.push(code);
        i = i + 1;
      } else if (code < 0x800) {
        bytes.push(0xc0 + Math.floor(code / 0x40));
        bytes.push(0x80 + (code % 0x40));
        i = i + 1;
      } else if (code >= 0xd800 && code < 0xdc00 && i + 1 < text.length) {
        var low = text.charCodeAt(i + 1);
        if (low >= 0xdc00 && low < 0xe000) {
          var point = 0x10000 + (code - 0xd800) * 0x400 + (low - 0xdc00);
          bytes.push(0xf0 + Math.floor(point / 0x40000));
          bytes.push(0x80 + (Math.floor(point / 0x1000) % 0x40));
          bytes.push(0x80 + (Math.floor(point / 0x40) % 0x40));
          bytes.push(0x80 + (point % 0x40));
          i = i + 2;
          continue;
        }
        bytes.push(0xef);
        bytes.push(0xbf);
        bytes.push(0xbd);
        i = i + 1;
      } else if (code >= 0xd800 && code < 0xe000) {
        bytes.push(0xef);
        bytes.push(0xbf);
        bytes.push(0xbd);
        i = i + 1;
      } else {
        bytes.push(0xe0 + Math.floor(code / 0x1000));
        bytes.push(0x80 + (Math.floor(code / 0x40) % 0x40));
        bytes.push(0x80 + (code % 0x40));
        i = i + 1;
      }
    }
    return bytes;
  }

  var SHA256_K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  ];

  function rotateRight(value, bits) {
    return (value >>> bits) | (value << (32 - bits));
  }

  function hex8(value) {
    var text = (value >>> 0).toString(16);
    while (text.length < 8) {
      text = "0" + text;
    }
    return text;
  }

  /* A compact, self-contained SHA-256 over a byte array. Bitwise 32-bit integer arithmetic is
   * platform-independent, so the digest is reproduceable in any engine and in any year. */
  function sha256Hex(bytes) {
    var message = [];
    for (var index = 0; index < bytes.length; index = index + 1) {
      message.push(bytes[index] & 0xff);
    }
    var bitLength = message.length * 8;
    message.push(0x80);
    while (message.length % 64 !== 56) {
      message.push(0);
    }
    var highBits = Math.floor(bitLength / 4294967296);
    var lowBits = bitLength % 4294967296;
    message.push((highBits >>> 24) & 0xff);
    message.push((highBits >>> 16) & 0xff);
    message.push((highBits >>> 8) & 0xff);
    message.push(highBits & 0xff);
    message.push((lowBits >>> 24) & 0xff);
    message.push((lowBits >>> 16) & 0xff);
    message.push((lowBits >>> 8) & 0xff);
    message.push(lowBits & 0xff);

    var h0 = 0x6a09e667;
    var h1 = 0xbb67ae85;
    var h2 = 0x3c6ef372;
    var h3 = 0xa54ff53a;
    var h4 = 0x510e527f;
    var h5 = 0x9b05688c;
    var h6 = 0x1f83d9ab;
    var h7 = 0x5be0cd19;

    var block = 0;
    while (block < message.length) {
      var schedule = [];
      for (var slot = 0; slot < 64; slot = slot + 1) {
        schedule.push(0);
      }
      for (slot = 0; slot < 16; slot = slot + 1) {
        var base = block + slot * 4;
        schedule[slot] =
          (message[base] << 24) |
          (message[base + 1] << 16) |
          (message[base + 2] << 8) |
          message[base + 3];
      }
      for (slot = 16; slot < 64; slot = slot + 1) {
        var w15 = schedule[slot - 15];
        var w2 = schedule[slot - 2];
        var s0 = rotateRight(w15, 7) ^ rotateRight(w15, 18) ^ (w15 >>> 3);
        var s1 = rotateRight(w2, 17) ^ rotateRight(w2, 19) ^ (w2 >>> 10);
        schedule[slot] = (schedule[slot - 16] + s0 + schedule[slot - 7] + s1) | 0;
      }
      var a = h0;
      var b = h1;
      var c = h2;
      var d = h3;
      var e = h4;
      var f = h5;
      var g = h6;
      var h = h7;
      for (slot = 0; slot < 64; slot = slot + 1) {
        var bigS1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
        var choose = (e & f) ^ (~e & g);
        var temp1 = (h + bigS1 + choose + SHA256_K[slot] + schedule[slot]) | 0;
        var bigS0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
        var majority = (a & b) ^ (a & c) ^ (b & c);
        var temp2 = (bigS0 + majority) | 0;
        h = g;
        g = f;
        f = e;
        e = (d + temp1) | 0;
        d = c;
        c = b;
        b = a;
        a = (temp1 + temp2) | 0;
      }
      h0 = (h0 + a) | 0;
      h1 = (h1 + b) | 0;
      h2 = (h2 + c) | 0;
      h3 = (h3 + d) | 0;
      h4 = (h4 + e) | 0;
      h5 = (h5 + f) | 0;
      h6 = (h6 + g) | 0;
      h7 = (h7 + h) | 0;
      block = block + 64;
    }
    return hex8(h0) + hex8(h1) + hex8(h2) + hex8(h3) + hex8(h4) + hex8(h5) + hex8(h6) + hex8(h7);
  }

  /* ==========================================================================================
   * Time: epoch milliseconds -> fixed-width ISO (mirrors timebase, K5)
   * ========================================================================================== */

  var MS_PER_SECOND = 1000;
  var MS_PER_MINUTE = 60000;
  var MS_PER_HOUR = 3600000;
  var MS_PER_DAY = 86400000;
  var EPOCH_SHIFT_DAYS = 719468;
  var DAYS_PER_ERA = 146097;

  /* mirrors: timebase.civil_from_days -- Hinnant's integer algorithm, no timezone database. */
  function civilFromDays(days) {
    var shifted = days + EPOCH_SHIFT_DAYS;
    var era = Math.floor(shifted / DAYS_PER_ERA);
    var dayOfEra = shifted - era * DAYS_PER_ERA;
    var yearOfEra = Math.floor(
      (dayOfEra - Math.floor(dayOfEra / 1460) + Math.floor(dayOfEra / 36524) - Math.floor(dayOfEra / 146096)) / 365
    );
    var year = yearOfEra + era * 400;
    var dayOfYear = dayOfEra - (365 * yearOfEra + Math.floor(yearOfEra / 4) - Math.floor(yearOfEra / 100));
    var monthPart = Math.floor((5 * dayOfYear + 2) / 153);
    var day = dayOfYear - Math.floor((153 * monthPart + 2) / 5) + 1;
    var month = monthPart + (monthPart < 10 ? 3 : -9);
    return [year + (month <= 2 ? 1 : 0), month, day];
  }

  /* mirrors: timebase.epoch_ms_to_iso -- the ISO string is derived from integers only. */
  function epochMsToIso(ms) {
    var days = Math.floor(ms / MS_PER_DAY);
    var rest = ms - days * MS_PER_DAY;
    var civil = civilFromDays(days);
    var hours = Math.floor(rest / MS_PER_HOUR);
    rest = rest - hours * MS_PER_HOUR;
    var minutes = Math.floor(rest / MS_PER_MINUTE);
    rest = rest - minutes * MS_PER_MINUTE;
    var seconds = Math.floor(rest / MS_PER_SECOND);
    var milli = rest - seconds * MS_PER_SECOND;
    return (
      padNumber(civil[0], 4) +
      "-" +
      padNumber(civil[1], 2) +
      "-" +
      padNumber(civil[2], 2) +
      "T" +
      padNumber(hours, 2) +
      ":" +
      padNumber(minutes, 2) +
      ":" +
      padNumber(seconds, 2) +
      "." +
      padNumber(milli, 3) +
      "Z"
    );
  }

  function padNumber(value, width) {
    var text = String(value);
    while (text.length < width) {
      text = "0" + text;
    }
    return text;
  }

  /* ==========================================================================================
   * Numeric primitives (mirrors detect._median .. detect._robust_z)
   * ========================================================================================== */

  function ascending(left, right) {
    return left - right;
  }

  /* mirrors: detect._median -- linear interpolation between the two middle values. */
  function median(values) {
    if (values.length === 0) {
      throw new Error("median of an empty window");
    }
    var ordered = values.slice().sort(ascending);
    var n = ordered.length;
    if (n === 1) {
      return ordered[0];
    }
    var position = 0.5 * (n - 1);
    var low = Math.floor(position);
    var high = low + 1;
    if (high >= n) {
      return ordered[n - 1];
    }
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low);
  }

  /* mirrors: detect._quantile */
  function quantile(values, fraction) {
    if (values.length === 0) {
      throw new Error("quantile of an empty window");
    }
    var ordered = values.slice().sort(ascending);
    var n = ordered.length;
    if (n === 1) {
      return ordered[0];
    }
    var position = fraction * (n - 1);
    var low = Math.floor(position);
    var high = low + 1;
    if (high >= n) {
      return ordered[n - 1];
    }
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low);
  }

  /* mirrors: detect._mean -- an explicit left-to-right loop, so the summation order is ours. */
  function mean(values) {
    var total = 0.0;
    for (var i = 0; i < values.length; i = i + 1) {
      total = total + values[i];
    }
    return total / values.length;
  }

  /* mirrors: detect._mad */
  function mad(values, medianValue) {
    var deviations = [];
    for (var i = 0; i < values.length; i = i + 1) {
      deviations.push(Math.abs(values[i] - medianValue));
    }
    return median(deviations);
  }

  /* mirrors: detect._mean_abs_deviation */
  function meanAbsDeviation(values, medianValue) {
    var total = 0.0;
    for (var i = 0; i < values.length; i = i + 1) {
      total = total + Math.abs(values[i] - medianValue);
    }
    return total / values.length;
  }

  /* mirrors: detect.robust_scale -- returns [scale, median]; the degenerate-MAD fallback and the
   * "a constant window cannot judge the point" rule are spelled out rather than left to a division. */
  function robustScale(values) {
    var medianValue = median(values);
    var deviation = mad(values, medianValue);
    if (deviation > 0) {
      return [MAD_TO_SIGMA * deviation, medianValue];
    }
    return [MAD_TO_SIGMA * meanAbsDeviation(values, medianValue), medianValue];
  }

  /* mirrors: detect._window -- the valid values of the trailing window [index-window+1, index]. */
  function trailingWindow(values, index, window) {
    var low = index - window + 1;
    if (low < 0) {
      low = 0;
    }
    var found = [];
    for (var position = low; position <= index; position = position + 1) {
      if (values[position] !== null) {
        found.push(values[position]);
      }
    }
    return found;
  }

  /* ==========================================================================================
   * Detector 1: rolling median + MAD (mirrors detect.rolling_mad_z)
   * ========================================================================================== */

  function rollingMadZ(values, window, k, minValid) {
    var hits = [];
    for (var index = 0; index < values.length; index = index + 1) {
      var target = values[index];
      if (target === null) {
        continue;
      }
      var windowValues = trailingWindow(values, index, window);
      if (windowValues.length < minValid) {
        continue;
      }
      var scaleAndMedian = robustScale(windowValues);
      if (scaleAndMedian[0] === 0) {
        continue;
      }
      var score = Math.abs(target - scaleAndMedian[1]) / scaleAndMedian[0];
      if (score > k) {
        hits.push([index, score]);
      }
    }
    return hits;
  }

  /* ==========================================================================================
   * Detector 2: rolling interquartile range (mirrors detect.rolling_iqr)
   * ========================================================================================== */

  function rollingIqr(values, window, iqrMult, minValid) {
    var hits = [];
    for (var index = 0; index < values.length; index = index + 1) {
      var target = values[index];
      if (target === null) {
        continue;
      }
      var windowValues = trailingWindow(values, index, window);
      if (windowValues.length < minValid) {
        continue;
      }
      var q1 = quantile(windowValues, 0.25);
      var q3 = quantile(windowValues, 0.75);
      var iqr = q3 - q1;
      var low;
      var high;
      var scale;
      if (iqr > 0) {
        low = q1 - iqrMult * iqr;
        high = q3 + iqrMult * iqr;
        scale = iqr;
      } else {
        var medianValue = median(windowValues);
        scale = meanAbsDeviation(windowValues, medianValue);
        if (scale === 0) {
          continue;
        }
        low = medianValue - iqrMult * scale;
        high = medianValue + iqrMult * scale;
      }
      if (target > high) {
        hits.push([index, (target - high) / scale]);
      } else if (target < low) {
        hits.push([index, (low - target) / scale]);
      }
    }
    return hits;
  }

  /* ==========================================================================================
   * Detector 3: STL residual z (mirrors detect._next_odd .. detect.stl_resid_z)
   * ========================================================================================== */

  /* mirrors: detect._next_odd */
  function nextOdd(value) {
    var number = Math.trunc(value);
    if (number < 1) {
      return 1;
    }
    return number % 2 ? number : number + 1;
  }

  /* mirrors: detect._tricube_table -- (1 - d^3)^3 for every integer distance up to dmax, written
   * with plain multiplication. */
  function tricubeTable(dmax) {
    var table = [];
    for (var distance = 0; distance <= dmax; distance = distance + 1) {
      var ratio = dmax > 0 ? distance / dmax : 0.0;
      var tricube = 1.0 - ratio * ratio * ratio;
      table.push(tricube * tricube * tricube);
    }
    return table;
  }

  /* mirrors: detect._loess */
  function loess(values, window, weights) {
    var n = values.length;
    var half = Math.floor(window / 2);
    var tables = {};
    var fitted = [];
    for (var fill = 0; fill < n; fill = fill + 1) {
      fitted.push(null);
    }
    for (var index = 0; index < n; index = index + 1) {
      if (values[index] === null) {
        continue;
      }
      var low = index - half;
      if (low < 0) {
        low = 0;
      }
      var high = index + half;
      if (high > n - 1) {
        high = n - 1;
      }
      if (high === low) {
        fitted[index] = values[index];
        continue;
      }
      var dmax = Math.max(index - low, high - index);
      var table = tables[dmax];
      if (table === undefined) {
        table = tricubeTable(dmax);
        tables[dmax] = table;
      }
      var sw = 0.0;
      var swx = 0.0;
      var swy = 0.0;
      var swxx = 0.0;
      var swxy = 0.0;
      for (var position = low; position <= high; position = position + 1) {
        var value = values[position];
        if (value === null) {
          continue;
        }
        var offset = position - index;
        var weight = offset < 0 ? table[-offset] : table[offset];
        if (weights !== null) {
          weight = weight * weights[position];
        }
        var x = offset;
        sw = sw + weight;
        swx = swx + weight * x;
        swy = swy + weight * value;
        swxx = swxx + weight * x * x;
        swxy = swxy + weight * x * value;
      }
      if (sw === 0) {
        continue;
      }
      var determinant = sw * swxx - swx * swx;
      if (determinant === 0) {
        fitted[index] = swy / sw;
      } else {
        var slope = (sw * swxy - swx * swy) / determinant;
        var intercept = (swy - slope * swx) / sw;
        fitted[index] = intercept;
      }
    }
    return fitted;
  }

  /* mirrors: detect._seasonal_curve -- phases come from the grid index, and the phase axis is
   * tripled before smoothing so the cycle wrap is continuous. */
  function seasonalCurve(detrended, positions, periodPoints, weights, window) {
    var totals = [];
    var counts = [];
    for (var fill = 0; fill < periodPoints; fill = fill + 1) {
      totals.push(0.0);
      counts.push(0.0);
    }
    for (var index = 0; index < detrended.length; index = index + 1) {
      var value = detrended[index];
      if (value === null) {
        continue;
      }
      var phase = positions[index] % periodPoints;
      var weight = weights === null ? 1.0 : weights[index];
      totals[phase] = totals[phase] + weight * value;
      counts[phase] = counts[phase] + weight;
    }
    var phaseMeans = [];
    for (var phaseIndex = 0; phaseIndex < periodPoints; phaseIndex = phaseIndex + 1) {
      if (counts[phaseIndex] > 0) {
        phaseMeans.push(totals[phaseIndex] / counts[phaseIndex]);
      } else {
        phaseMeans.push(0.0);
      }
    }
    var tripled = phaseMeans.concat(phaseMeans).concat(phaseMeans);
    var smoothed = loess(tripled, window, null);
    var curve = [];
    for (var middle = 0; middle < periodPoints; middle = middle + 1) {
      var fitted = smoothed[periodPoints + middle];
      curve.push(fitted === null ? phaseMeans[middle] : fitted);
    }
    return curve;
  }

  /* mirrors: detect._bisquare_weights -- (1 - u^2)^2 by pure multiplication. */
  function bisquareWeights(residual) {
    var deviations = [];
    for (var index = 0; index < residual.length; index = index + 1) {
      if (residual[index] !== null) {
        deviations.push(Math.abs(residual[index]));
      }
    }
    if (deviations.length === 0) {
      var ones = [];
      for (var fill = 0; fill < residual.length; fill = fill + 1) {
        ones.push(1.0);
      }
      return ones;
    }
    var scale = 6.0 * median(deviations);
    var weights = [];
    for (var position = 0; position < residual.length; position = position + 1) {
      var value = residual[position];
      if (value === null || scale === 0) {
        weights.push(1.0);
        continue;
      }
      var ratio = Math.abs(value) / scale;
      if (ratio >= 1.0) {
        weights.push(0.0);
      } else {
        var factor = 1.0 - ratio * ratio;
        weights.push(factor * factor);
      }
    }
    return weights;
  }

  /* mirrors: detect.stl_residual */
  function stlResidual(values, positions, periodPoints, inner, outer) {
    var n = values.length;
    if (periodPoints <= 1) {
      var present = [];
      for (var scan = 0; scan < n; scan = scan + 1) {
        if (values[scan] !== null) {
          present.push(values[scan]);
        }
      }
      var seasonalValue = present.length ? mean(present) : 0.0;
      var detrended = [];
      for (var flat = 0; flat < n; flat = flat + 1) {
        detrended.push(values[flat] === null ? null : values[flat] - seasonalValue);
      }
      var trendOnly = loess(detrended, nextOdd(Math.max(3, Math.min(n, 24))), null);
      var residualOnly = [];
      for (var plain = 0; plain < n; plain = plain + 1) {
        residualOnly.push(
          detrended[plain] !== null && trendOnly[plain] !== null ? detrended[plain] - trendOnly[plain] : null
        );
      }
      return residualOnly;
    }

    var trendWindow = nextOdd(Math.floor((3 * periodPoints) / 2));
    var seasonalWindow = nextOdd(Math.floor(periodPoints / 3));
    var weights = [];
    for (var seed = 0; seed < n; seed = seed + 1) {
      weights.push(1.0);
    }
    var trend = loess(values, trendWindow, null);
    var seasonal = [];
    for (seed = 0; seed < n; seed = seed + 1) {
      seasonal.push(0.0);
    }
    var residual = values.slice();
    for (var pass = 0; pass <= outer; pass = pass + 1) {
      for (var iteration = 0; iteration < inner; iteration = iteration + 1) {
        var withoutTrend = [];
        for (var step = 0; step < n; step = step + 1) {
          withoutTrend.push(
            values[step] !== null && trend[step] !== null ? values[step] - trend[step] : null
          );
        }
        var curve = seasonalCurve(withoutTrend, positions, periodPoints, weights, seasonalWindow);
        for (step = 0; step < n; step = step + 1) {
          seasonal[step] = curve[positions[step] % periodPoints];
        }
        var withoutSeason = [];
        for (step = 0; step < n; step = step + 1) {
          withoutSeason.push(values[step] === null ? null : values[step] - seasonal[step]);
        }
        trend = loess(withoutSeason, trendWindow, weights);
      }
      residual = [];
      for (var last = 0; last < n; last = last + 1) {
        residual.push(
          values[last] !== null && trend[last] !== null
            ? values[last] - trend[last] - seasonal[last]
            : null
        );
      }
      weights = bisquareWeights(residual);
    }
    return residual;
  }

  /* mirrors: detect.stl_resid_z -- the residual is scored by the same rolling median/MAD code. */
  function stlResidZ(values, positions, periodPoints, inner, outer, window, k, minValid) {
    return rollingMadZ(stlResidual(values, positions, periodPoints, inner, outer), window, k, minValid);
  }

  /* ==========================================================================================
   * Detector 4: rules (mirrors detect.rules / _run_hits / _cusum_hits)
   * ========================================================================================== */

  function rules(values, spec) {
    var hits = [];
    var staticThreshold = spec.static_threshold;
    if (staticThreshold !== null) {
      for (var index = 0; index < values.length; index = index + 1) {
        var value = values[index];
        if (value === null) {
          continue;
        }
        if (Math.abs(value) > staticThreshold) {
          hits.push([index, Math.abs(value) - staticThreshold, "static_threshold"]);
        }
      }
    }

    var pctJump = spec.pct_jump;
    for (var position = 1; position < values.length; position = position + 1) {
      var previous = values[position - 1];
      var current = values[position];
      if (previous === null || current === null || previous === 0) {
        continue;
      }
      var ratio = current / previous;
      var jump = ratio - 1.0;
      if (jump < 0) {
        jump = -jump;
      }
      if (jump > pctJump) {
        hits.push([position, jump, "pct_jump"]);
      }
    }

    runHits(values, spec.missing_run, true, hits);
    runHits(values, spec.missing_run, false, hits);
    cusumHits(values, spec.cusum_k, spec.cusum_h, hits);
    return hits;
  }

  /* mirrors: detect._run_hits */
  function runHits(values, minimum, missing, hits) {
    var start = null;
    for (var index = 0; index <= values.length; index = index + 1) {
      var inside =
        index < values.length && (missing ? values[index] === null : values[index] === 0.0);
      if (inside && start === null) {
        start = index;
      } else if (!inside && start !== null) {
        var length = index - start;
        if (length >= minimum) {
          var name = missing ? "missing_run" : "zero_run";
          for (var position = start; position < index; position = position + 1) {
            hits.push([position, length, name]);
          }
        }
        start = null;
      }
    }
  }

  /* mirrors: detect._cusum_hits -- two-sided CUSUM over consecutive differences, standardised by
   * the differences' own robust scale, both accumulators restarting on an alarm. */
  function cusumHits(values, cusumK, cusumH, hits) {
    var differences = [];
    for (var index = 1; index < values.length; index = index + 1) {
      var previous = values[index - 1];
      var current = values[index];
      if (previous === null || current === null) {
        continue;
      }
      differences.push([index, current - previous]);
    }
    if (differences.length === 0) {
      return;
    }
    var scaleValues = [];
    for (var scan = 0; scan < differences.length; scan = scan + 1) {
      scaleValues.push(differences[scan][1]);
    }
    var scale = robustScale(scaleValues)[0];
    var present = [];
    for (scan = 0; scan < values.length; scan = scan + 1) {
      if (values[scan] !== null) {
        present.push(values[scan]);
      }
    }
    var reference = present.length ? robustScale(present)[0] : 0.0;
    if (scale === 0 || scale < DECIMAL_RESOLUTION_FRACTION * reference) {
      return;
    }
    var positive = 0.0;
    var negative = 0.0;
    for (var step = 0; step < differences.length; step = step + 1) {
      var standardized = differences[step][1] / scale;
      positive = positive + standardized - cusumK;
      if (positive < 0.0) {
        positive = 0.0;
      }
      negative = negative - standardized - cusumK;
      if (negative < 0.0) {
        negative = 0.0;
      }
      var score = positive > negative ? positive : negative;
      if (score > cusumH) {
        hits.push([differences[step][0], score, "cusum"]);
        positive = 0.0;
        negative = 0.0;
      }
    }
  }

  /* ==========================================================================================
   * Grid placement (mirrors detect.dominant_interval / detect.grid_positions)
   * ========================================================================================== */

  /* mirrors: detect.dominant_interval -- the most frequent positive gap, shortest on a tie. */
  function dominantInterval(stamps) {
    var counts = new Map();
    for (var index = 1; index < stamps.length; index = index + 1) {
      var delta = stamps[index] - stamps[index - 1];
      if (delta > 0) {
        counts.set(delta, (counts.has(delta) ? counts.get(delta) : 0) + 1);
      }
    }
    if (counts.size === 0) {
      return null;
    }
    var keys = [];
    counts.forEach(function (_count, delta) {
      keys.push(delta);
    });
    keys.sort(function (left, right) {
      if (counts.get(left) !== counts.get(right)) {
        return counts.get(right) - counts.get(left);
      }
      return left - right;
    });
    return keys[0];
  }

  /* mirrors: detect.grid_positions -- the grid index of every sample, from the timestamps alone. */
  function gridPositions(rows) {
    var stamps = [];
    for (var index = 0; index < rows.length; index = index + 1) {
      stamps.push(rows[index][0]);
    }
    var cadence = dominantInterval(stamps);
    if (cadence === null) {
      var identity = [];
      for (index = 0; index < rows.length; index = index + 1) {
        identity.push(index);
      }
      return identity;
    }
    var start = stamps[0];
    var positions = [];
    for (index = 0; index < stamps.length; index = index + 1) {
      positions.push(Math.floor((stamps[index] - start) / cadence));
    }
    return positions;
  }

  /* ==========================================================================================
   * Episodes (mirrors episodes.merge_episodes / order_episodes / assign_ids / severity_key)
   * ========================================================================================== */

  function finishEpisode(seriesId, detector, thresholdRef, points, decimals) {
    var peak = 0.0;
    for (var index = 0; index < points.length; index = index + 1) {
      if (points[index][2] > peak) {
        peak = points[index][2];
      }
    }
    var startMs = points[0][0];
    var endMs = points[points.length - 1][0];
    return {
      episode_id: "",
      series_id: seriesId,
      detector: detector,
      start: epochMsToIso(startMs),
      end: epochMsToIso(endMs),
      duration_ms: endMs - startMs,
      peak_score_q: quantize(peak, decimals),
      n_points: points.length,
      start_row: points[0][1],
      end_row: points[points.length - 1][1],
      threshold_ref: thresholdRef
    };
  }

  /* mirrors: episodes.merge_episodes -- time domain, `<= max_gap_ms` merges. */
  function mergeEpisodes(seriesId, detector, thresholdRef, points, maxGapMs, decimals) {
    var episodes = [];
    var current = [];
    for (var index = 0; index < points.length; index = index + 1) {
      var point = points[index];
      if (current.length && point[0] - current[current.length - 1][0] > maxGapMs) {
        episodes.push(finishEpisode(seriesId, detector, thresholdRef, current, decimals));
        current = [];
      }
      current.push(point);
    }
    if (current.length) {
      episodes.push(finishEpisode(seriesId, detector, thresholdRef, current, decimals));
    }
    return episodes;
  }

  /* mirrors: episodes.severity_key -- a total order over integers and strings, never a raw float. */
  function severityCompare(left, right) {
    if (left.peak_score_q !== right.peak_score_q) {
      return right.peak_score_q - left.peak_score_q;
    }
    if (left.duration_ms !== right.duration_ms) {
      return right.duration_ms - left.duration_ms;
    }
    if (left.start_row !== right.start_row) {
      return left.start_row - right.start_row;
    }
    return codePointCompare(left.detector, right.detector);
  }

  function assignIds(episodes) {
    var seen = {};
    for (var index = 0; index < episodes.length; index = index + 1) {
      var seriesId = episodes[index].series_id;
      seen[seriesId] = (seen[seriesId] || 0) + 1;
      episodes[index].episode_id = seriesId + "-E" + zeroPad(seen[seriesId], 3);
    }
    return episodes;
  }

  /* ==========================================================================================
   * The recomputation itself
   * ========================================================================================== */

  function toFloat(value) {
    if (value === null || value === undefined) {
      return value;
    }
    if (typeof value === "number") {
      return value;
    }
    return parseFloat(value);
  }

  /* An inlined sample is the decimal *text* the kernel parsed, never a float literal (K3). Both
   * sides turn that text into the nearest double, and both do it correctly rounded, so the mirror
   * works on the same bits Python worked on -- which is the assumption the whole parity gate rests
   * on, and the one `verify` re-checks on every run. */
  function sampleValue(text) {
    return text === null ? null : parseFloat(text);
  }

  /* mirrors: detect.resolve_spec over the dumped run-spec -- decimals arrive as fixed-point
   * strings (K3), so they are parsed back to the number the build actually used. */
  function readSpec(params) {
    return {
      rolling_mad_z: {
        window: params.rolling_mad_z.window,
        k: toFloat(params.rolling_mad_z.k),
        min_valid: params.rolling_mad_z.min_valid
      },
      rolling_iqr: {
        window: params.rolling_iqr.window,
        iqr_mult: toFloat(params.rolling_iqr.iqr_mult),
        min_valid: params.rolling_iqr.min_valid
      },
      stl_resid_z: {
        inner: params.stl_resid_z.inner,
        outer: params.stl_resid_z.outer,
        window: params.stl_resid_z.window,
        k: toFloat(params.stl_resid_z.k),
        min_valid: params.stl_resid_z.min_valid
      },
      rules: {
        static_threshold: toFloat(params.rules.static_threshold),
        pct_jump: toFloat(params.rules.pct_jump),
        missing_run: params.rules.missing_run,
        cusum_k: toFloat(params.rules.cusum_k),
        cusum_h: toFloat(params.rules.cusum_h)
      }
    };
  }

  /* mirrors: detect.threshold_refs -- the family's dumped parameter block, one representation. */
  function thresholdRefs(params) {
    var refs = {};
    refs.rolling_mad_z = params.rolling_mad_z;
    refs.rolling_iqr = params.rolling_iqr;
    refs.stl_resid_z = params.stl_resid_z;
    refs.rules = params.rules;
    for (var index = 0; index < RULE_NAMES.length; index = index + 1) {
      refs["rules." + RULE_NAMES[index]] = params.rules;
    }
    return refs;
  }

  function pointOrder(left, right) {
    if (left[0] !== right[0]) {
      return left[0] - right[0];
    }
    return left[1] - right[1];
  }

  function recordHits(buckets, detector, rows, hits) {
    for (var index = 0; index < hits.length; index = index + 1) {
      var point = hits[index];
      var row = rows[point[0]];
      buckets[detector].push([row[0], row[2], point[1]]);
    }
  }

  /* mirrors: detect.run_detectors + episodes.build_episodes + detect.summarize, in one pass. */
  function recompute(payload) {
    var run = payload.run;
    var decimals = run.quant_decimals;
    var params = run.params;
    var spec = readSpec(params);
    var refs = thresholdRefs(params);
    var periodPoints = params.period_points;

    var seriesList = payload.series.slice();
    seriesList.sort(function (left, right) {
      return codePointCompare(left.series_id, right.series_id);
    });

    var detections = {};
    for (var position = 0; position < seriesList.length; position = position + 1) {
      var seriesId = seriesList[position].series_id;
      var rows = seriesList[position].rows;
      var values = [];
      for (var row = 0; row < rows.length; row = row + 1) {
        values.push(sampleValue(rows[row][1]));
      }
      var positions = gridPositions(rows);
      var buckets = { rolling_mad_z: [], rolling_iqr: [], stl_resid_z: [] };
      recordHits(
        buckets,
        "rolling_mad_z",
        rows,
        rollingMadZ(values, spec.rolling_mad_z.window, spec.rolling_mad_z.k, spec.rolling_mad_z.min_valid)
      );
      recordHits(
        buckets,
        "rolling_iqr",
        rows,
        rollingIqr(values, spec.rolling_iqr.window, spec.rolling_iqr.iqr_mult, spec.rolling_iqr.min_valid)
      );
      recordHits(
        buckets,
        "stl_resid_z",
        rows,
        stlResidZ(
          values,
          positions,
          periodPoints,
          spec.stl_resid_z.inner,
          spec.stl_resid_z.outer,
          spec.stl_resid_z.window,
          spec.stl_resid_z.k,
          spec.stl_resid_z.min_valid
        )
      );
      var ruleHits = rules(values, spec.rules);
      for (var hit = 0; hit < ruleHits.length; hit = hit + 1) {
        var name = "rules." + ruleHits[hit][2];
        if (!Object.prototype.hasOwnProperty.call(buckets, name)) {
          buckets[name] = [];
        }
        recordHits(buckets, name, rows, [ruleHits[hit]]);
      }
      detections[seriesId] = buckets;
    }

    var episodes = [];
    var seriesIds = Object.keys(detections).sort(codePointCompare);
    for (position = 0; position < seriesIds.length; position = position + 1) {
      var bucketSeries = seriesIds[position];
      var detectorNames = Object.keys(detections[bucketSeries]).sort(codePointCompare);
      for (var name2 = 0; name2 < detectorNames.length; name2 = name2 + 1) {
        var detector = detectorNames[name2];
        var points = detections[bucketSeries][detector].slice();
        points.sort(pointOrder);
        if (!points.length) {
          continue;
        }
        episodes = episodes.concat(
          mergeEpisodes(
            bucketSeries,
            detector,
            Object.prototype.hasOwnProperty.call(refs, detector) ? refs[detector] : {},
            points,
            params.max_gap_ms,
            decimals
          )
        );
      }
    }
    episodes.sort(severityCompare);
    assignIds(episodes);

    var summary = summarize(detections, episodes);
    var anomalySet = {
      schema_version: run.schema_version,
      run: run,
      episodes: episodes,
      summary: summary
    };
    var canonical = canonicalJsonText(anomalySet);
    return {
      canonical: canonical,
      digest: sha256Hex(utf8Bytes(canonical)),
      points: detectionPoints(detections, decimals)
    };
  }

  /* mirrors: detect.summarize */
  function summarize(detections, episodes) {
    var episodesByDetector = {};
    var episodesBySeries = {};
    for (var index = 0; index < episodes.length; index = index + 1) {
      var detectorKey = episodes[index].detector;
      episodesByDetector[detectorKey] = (episodesByDetector[detectorKey] || 0) + 1;
      var seriesKey = episodes[index].series_id;
      episodesBySeries[seriesKey] = (episodesBySeries[seriesKey] || 0) + 1;
    }
    var names = [];
    var known = {};
    var seriesIds = Object.keys(detections).sort(codePointCompare);
    for (index = 0; index < seriesIds.length; index = index + 1) {
      var detectorNames = Object.keys(detections[seriesIds[index]]);
      for (var name = 0; name < detectorNames.length; name = name + 1) {
        if (!Object.prototype.hasOwnProperty.call(known, detectorNames[name])) {
          known[detectorNames[name]] = true;
          names.push(detectorNames[name]);
        }
      }
    }
    names.sort(codePointCompare);
    var detectionsByDetector = {};
    var nDetections = 0;
    for (index = 0; index < names.length; index = index + 1) {
      var count = 0;
      for (var series = 0; series < seriesIds.length; series = series + 1) {
        var bucket = detections[seriesIds[series]];
        if (Object.prototype.hasOwnProperty.call(bucket, names[index])) {
          count = count + bucket[names[index]].length;
        }
      }
      detectionsByDetector[names[index]] = count;
      nDetections = nDetections + count;
    }
    return {
      n_episodes: episodes.length,
      n_detections: nDetections,
      episodes_by_detector: episodesByDetector,
      episodes_by_series: episodesBySeries,
      detections_by_detector: detectionsByDetector
    };
  }

  /* The per-point form of the detector output, in fixed point: the point-set comparison the badge
   * and the tamper probe both need. Flattened in (series, detector) order, then time order. */
  function detectionPoints(detections, decimals) {
    var out = [];
    var seriesIds = Object.keys(detections).sort(codePointCompare);
    for (var index = 0; index < seriesIds.length; index = index + 1) {
      var detectorNames = Object.keys(detections[seriesIds[index]]).sort(codePointCompare);
      for (var name = 0; name < detectorNames.length; name = name + 1) {
        var points = detections[seriesIds[index]][detectorNames[name]].slice();
        points.sort(pointOrder);
        var quantized = [];
        for (var point = 0; point < points.length; point = point + 1) {
          quantized.push([
            points[point][0],
            points[point][1],
            quantize(points[point][2], decimals)
          ]);
        }
        out.push({
          series_id: seriesIds[index],
          detector: detectorNames[name],
          points: quantized
        });
      }
    }
    return out;
  }

  /* ==========================================================================================
   * Verdict: byte comparison first, then the first differing point (plan/03 M3)
   * ========================================================================================== */

  function firstByteDifference(left, right) {
    var a = utf8Bytes(left);
    var b = utf8Bytes(right);
    var limit = Math.min(a.length, b.length);
    for (var index = 0; index < limit; index = index + 1) {
      if (a[index] !== b[index]) {
        return index;
      }
    }
    if (a.length !== b.length) {
      return limit;
    }
    return -1;
  }

  function samePoint(left, right) {
    return left[0] === right[0] && left[1] === right[1] && left[2] === right[2];
  }

  /* The report is the whole product of the check: VERIFIED, or MISMATCH plus the first place the
   * recomputation disagrees with the build (a point if the points differ, a block if the detector
   * sets differ, a byte offset when only the serialisation moved). */
  function verdict(result, expected, tamper) {
    var report = {
      verified: false,
      digest: result.digest,
      expected_digest: expected.sha256,
      canonical_equal: result.canonical === expected.canonical,
      first_byte_diff: firstByteDifference(result.canonical, expected.canonical),
      first_point_diff: null,
      tamper: tamper === undefined ? null : tamper
    };
    var expectedPoints = expected.points || [];
    var actualPoints = result.points || [];
    var blocks = Math.min(expectedPoints.length, actualPoints.length);
    for (var index = 0; index < blocks && report.first_point_diff === null; index = index + 1) {
      var want = expectedPoints[index];
      var got = actualPoints[index];
      if (want.series_id !== got.series_id || want.detector !== got.detector) {
        report.first_point_diff = {
          kind: "block",
          index: index,
          expected_series: want.series_id,
          expected_detector: want.detector,
          actual_series: got.series_id,
          actual_detector: got.detector
        };
        break;
      }
      var shared = Math.min(want.points.length, got.points.length);
      for (var point = 0; point < shared; point = point + 1) {
        if (!samePoint(want.points[point], got.points[point])) {
          report.first_point_diff = {
            kind: "point",
            series_id: want.series_id,
            detector: want.detector,
            index: point,
            expected: want.points[point],
            actual: got.points[point]
          };
          break;
        }
      }
      if (report.first_point_diff === null && want.points.length !== got.points.length) {
        report.first_point_diff = {
          kind: "count",
          series_id: want.series_id,
          detector: want.detector,
          index: shared,
          expected_n: want.points.length,
          actual_n: got.points.length
        };
      }
    }
    if (report.first_point_diff === null && expectedPoints.length !== actualPoints.length) {
      report.first_point_diff = {
        kind: "blocks",
        index: blocks,
        expected_n: expectedPoints.length,
        actual_n: actualPoints.length
      };
    }
    report.verified = report.canonical_equal && report.digest === expected.sha256;
    return report;
  }

  return {
    utf8Bytes: utf8Bytes,
    sha256Hex: sha256Hex,
    canonicalJsonText: canonicalJsonText,
    fixedToStr: fixedToStr,
    quantize: quantize,
    recompute: recompute,
    verdict: verdict
  };
})();
