/// ISO 6346 container number validation (client-side mirror of the API's
/// `iso6346_check_digit`). Format: 4 letters (owner code + category) + 6 serial
/// digits + 1 check digit, e.g. `CSQU3054383`.
class Iso6346 {
  Iso6346._();

  static final RegExp _format = RegExp(r'^[A-Z]{4}\d{7}$');
  static final RegExp _prefixFormat = RegExp(r'^[A-Z]{4}\d{6}$');

  /// Letter values skip multiples of 11 (A=10, B=12, ..., K=21, L=23, ...).
  static final Map<String, int> _letterValues = _buildLetterValues();

  static Map<String, int> _buildLetterValues() {
    final m = <String, int>{};
    var v = 10;
    for (final ch in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('')) {
      if (v % 11 == 0) v++;
      m[ch] = v;
      v++;
    }
    return m;
  }

  static String normalise(String input) =>
      input.replaceAll(RegExp(r'[\s-]'), '').toUpperCase();

  /// Expected check digit for the first 10 characters, or null if the prefix
  /// is malformed.
  static int? checkDigit(String number) {
    final n = normalise(number);
    if (n.length < 10) return null;
    final prefix = n.substring(0, 10);
    if (!_prefixFormat.hasMatch(prefix)) return null;
    var total = 0;
    for (var i = 0; i < 10; i++) {
      final ch = prefix[i];
      final val = _letterValues[ch] ?? int.parse(ch);
      total += val * (1 << i);
    }
    return (total % 11) % 10;
  }

  static bool hasValidFormat(String number) =>
      _format.hasMatch(normalise(number));

  static bool isValid(String number) {
    final n = normalise(number);
    if (!hasValidFormat(n)) return false;
    final cd = checkDigit(n);
    return cd != null && cd == int.parse(n[10]);
  }

  /// Returns a localisation key describing the problem, or null when valid.
  static String? validationError(String number) {
    final n = normalise(number);
    if (!hasValidFormat(n)) return 'container_invalid_format';
    if (!isValid(n)) return 'container_invalid_check';
    return null;
  }
}
