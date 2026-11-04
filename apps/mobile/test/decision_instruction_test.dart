import 'package:flutter_test/flutter_test.dart';
import 'package:kifaru_mobile/core/decision_instruction.dart';
import 'package:kifaru_mobile/l10n/strings.dart';

void main() {
  const en = L10n('en');
  const sw = L10n('sw');

  group('instructionFor', () {
    test('GREEN -> Continue / Endelea', () {
      final i = instructionFor('GREEN');
      expect(i.clearance, Clearance.green);
      expect(i.key, 'instr_continue');
      expect(en.t(i.key, i.params), 'Continue');
      expect(sw.t(i.key, i.params), 'Endelea');
    });

    test('AMBER with a known static lane names the lane', () {
      final i = instructionFor('amber', staticLaneNo: 9);
      expect(i.clearance, Clearance.amber);
      expect(i.key, 'instr_static_scale');
      expect(en.t(i.key, i.params), 'Proceed to static scale - lane 9');
      expect(sw.t(i.key, i.params), contains('njia 9'));
    });

    test('AMBER without a static lane falls back to the lane-less text', () {
      final i = instructionFor('AMBER');
      expect(i.key, 'instr_static_scale_nolane');
      expect(en.t(i.key, i.params), 'Proceed to static scale');
      expect(en.t(i.key, i.params), isNot(contains('{lane}')));
    });

    test('RED -> Stop for inspection / Simama kwa ukaguzi', () {
      final i = instructionFor('RED');
      expect(i.clearance, Clearance.red);
      expect(en.t(i.key, i.params), 'Stop for inspection');
      expect(sw.t(i.key, i.params), 'Simama kwa ukaguzi');
    });

    test('null, empty and unknown decisions -> awaiting', () {
      for (final d in [null, '', 'PURPLE', 'green ']) {
        final i = instructionFor(d);
        if (d == 'green ') {
          expect(i.clearance, Clearance.green); // trimmed + case-insensitive
        } else {
          expect(i.clearance, Clearance.unknown, reason: 'decision=$d');
          expect(i.key, 'instr_awaiting');
        }
      }
    });

    test('decision labels exist in both languages', () {
      expect(en.decision('GREEN'), 'GREEN');
      expect(sw.decision('GREEN'), 'KIJANI');
      expect(sw.decision('AMBER'), 'MANJANO');
      expect(sw.decision('RED'), 'NYEKUNDU');
      expect(sw.decision(null), isNot('awaiting_decision'));
    });

    test('every instruction key is translated (no raw keys leak to drivers)', () {
      for (final key in [
        'instr_continue',
        'instr_static_scale',
        'instr_static_scale_nolane',
        'instr_stop',
        'instr_awaiting',
      ]) {
        expect(en.t(key), isNot(key), reason: 'en missing $key');
        expect(sw.t(key), isNot(key), reason: 'sw missing $key');
        expect(sw.t(key), isNot(en.t(key)), reason: 'sw not translated: $key');
      }
    });

    test('Instruction equality is value-based', () {
      expect(instructionFor('GREEN'), instructionFor('green'));
      expect(instructionFor('AMBER', staticLaneNo: 2),
          isNot(instructionFor('AMBER', staticLaneNo: 3)));
    });
  });

  group('normalisePlate', () {
    test('strips spaces and punctuation, upper-cases', () {
      expect(normalisePlate('kbz 123a'), 'KBZ123A');
      expect(normalisePlate('KBZ-123A'), 'KBZ123A');
      expect(normalisePlate(null), '');
    });
  });

  group('L10n placeholders', () {
    test('substitutes multiple params and tolerates nulls', () {
      expect(en.t('slot_in_hours', {'h': 1, 'm': 5}), 'Slot in 1 h 5 min');
      expect(en.t('gps_queued', {'n': null}), 'GPS queued ()');
    });
    test('falls back to English then to the key', () {
      expect(const L10n('xx').t('instr_stop'), 'Stop for inspection');
      expect(en.t('no_such_key'), 'no_such_key');
    });
  });
}
