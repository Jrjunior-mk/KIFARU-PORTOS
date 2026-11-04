/// Maps a clearance decision (GREEN / AMBER / RED) to the instruction shown
/// and spoken to the driver. Pure Dart so it can be unit tested without
/// Flutter.
enum Clearance { green, amber, red, unknown }

Clearance clearanceFrom(String? decision) {
  switch (decision?.trim().toUpperCase()) {
    case 'GREEN':
      return Clearance.green;
    case 'AMBER':
      return Clearance.amber;
    case 'RED':
      return Clearance.red;
    default:
      return Clearance.unknown;
  }
}

class Instruction {
  const Instruction(this.clearance, this.key, [this.params = const {}]);

  final Clearance clearance;

  /// Localisation key (see `lib/l10n/strings.dart`).
  final String key;
  final Map<String, Object?> params;

  @override
  bool operator ==(Object other) =>
      other is Instruction &&
      other.clearance == clearance &&
      other.key == key &&
      other.params.toString() == params.toString();

  @override
  int get hashCode => Object.hash(clearance, key, params.toString());

  @override
  String toString() => 'Instruction($clearance, $key, $params)';
}

/// * GREEN  -> "Continue"
/// * AMBER  -> "Proceed to static scale - lane N" (N = the station's static
///             lane when known; otherwise the lane-less variant)
/// * RED    -> "Stop for inspection"
/// * other  -> "Drive on; await decision"
Instruction instructionFor(String? decision, {int? staticLaneNo}) {
  switch (clearanceFrom(decision)) {
    case Clearance.green:
      return const Instruction(Clearance.green, 'instr_continue');
    case Clearance.amber:
      if (staticLaneNo != null) {
        return Instruction(
            Clearance.amber, 'instr_static_scale', {'lane': staticLaneNo});
      }
      return const Instruction(Clearance.amber, 'instr_static_scale_nolane');
    case Clearance.red:
      return const Instruction(Clearance.red, 'instr_stop');
    case Clearance.unknown:
      return const Instruction(Clearance.unknown, 'instr_awaiting');
  }
}

/// Normalises a plate for comparing WebSocket payloads with the selected
/// vehicle (`KBZ 123A` == `kbz-123a`).
String normalisePlate(String? plate) =>
    (plate ?? '').toUpperCase().replaceAll(RegExp(r'[^A-Z0-9]'), '');
