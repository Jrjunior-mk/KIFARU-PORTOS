import 'package:intl/intl.dart';

/// Formats a UTC timestamp in the device's local zone (Africa/Nairobi for the
/// target users). Storage is UTC; display is local - same rule as the web UI.
String fmtLocal(DateTime? utc, {bool withDate = true}) {
  if (utc == null) return '-';
  final local = utc.toLocal();
  return (withDate ? DateFormat('dd MMM HH:mm') : DateFormat('HH:mm'))
      .format(local);
}

String fmtTonnes(int kg, {int decimals = 1}) =>
    (kg / 1000.0).toStringAsFixed(decimals);

String fmtKg(int kg) => NumberFormat('#,##0').format(kg);
