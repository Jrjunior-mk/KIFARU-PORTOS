import 'package:flutter_test/flutter_test.dart';
import 'package:kifaru_mobile/core/iso6346.dart';

void main() {
  group('Iso6346', () {
    test('computes the check digit for known container numbers', () {
      // CSQU 305438 3 is the canonical example in ISO 6346 literature.
      expect(Iso6346.checkDigit('CSQU3054383'), 3);
      // Hand-computed: H=18 L=23 X=36 U=32 1 2 3 4 5 6 -> sum 5600 -> 5600 % 11 = 1.
      expect(Iso6346.checkDigit('HLXU1234561'), 1);
    });

    test('accepts valid numbers and normalises case, spaces and dashes', () {
      expect(Iso6346.isValid('CSQU3054383'), isTrue);
      expect(Iso6346.isValid('csqu 305438-3'), isTrue);
      expect(Iso6346.isValid('HLXU1234561'), isTrue);
      expect(Iso6346.validationError('CSQU3054383'), isNull);
    });

    test('rejects a wrong check digit', () {
      expect(Iso6346.isValid('CSQU3054380'), isFalse);
      expect(Iso6346.validationError('CSQU3054380'), 'container_invalid_check');
      expect(Iso6346.validationError('HLXU1234569'), 'container_invalid_check');
    });

    test('rejects malformed input (format error takes precedence)', () {
      expect(Iso6346.validationError('CSQ3054383'), 'container_invalid_format');
      expect(Iso6346.validationError('CSQU30543'), 'container_invalid_format');
      expect(Iso6346.validationError('1234567890A'), 'container_invalid_format');
      expect(Iso6346.validationError('CSQU30543831'), 'container_invalid_format');
      expect(Iso6346.checkDigit('CSQU'), isNull);
      expect(Iso6346.checkDigit('CSQU30543A3'), isNull);
    });

    test('letter values skip multiples of 11 (A=10, B=12, L=23, V=34)', () {
      // AAAA000000 -> 10 * (1+2+4+8) = 150 -> 150 % 11 = 7 -> 7
      expect(Iso6346.checkDigit('AAAA0000007'), 7);
      // BBBB000000 -> 12 * 15 = 180 -> 180 % 11 = 4
      expect(Iso6346.checkDigit('BBBB0000004'), 4);
      // LLLL000000 -> 23 * 15 = 345 -> 345 % 11 = 4
      expect(Iso6346.checkDigit('LLLL0000004'), 4);
      // VVVV000000 -> 34 * 15 = 510 -> 510 % 11 = 4
      expect(Iso6346.checkDigit('VVVV0000004'), 4);
    });

    test('a remainder of 10 maps to check digit 0', () {
      // Search a serial whose weighted sum % 11 == 10 to exercise the % 10 rule.
      String? found;
      for (var n = 0; n < 1000 && found == null; n++) {
        final candidate = 'ABCU${n.toString().padLeft(6, '0')}';
        var total = 0;
        const letters = {'A': 10, 'B': 12, 'C': 13, 'U': 32};
        for (var i = 0; i < 10; i++) {
          final ch = candidate[i];
          total += (letters[ch] ?? int.parse(ch)) * (1 << i);
        }
        if (total % 11 == 10) found = candidate;
      }
      expect(found, isNotNull);
      expect(Iso6346.checkDigit('${found!}0'), 0);
      expect(Iso6346.isValid('${found}0'), isTrue);
    });
  });
}
