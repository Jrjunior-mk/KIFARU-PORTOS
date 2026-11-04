import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/app_settings.dart';

/// Shows the `source` of a weighing / ticket (`live`, `simulated`, `replay`).
/// Rule from the API description: simulated data is never presented as live,
/// so every weighing on screen carries this badge.
class SourceBadge extends StatelessWidget {
  const SourceBadge(this.source, {super.key, this.large = false});

  final String source;
  final bool large;

  @override
  Widget build(BuildContext context) {
    final l = context.watch<AppSettings>().l10n;
    final s = source.toLowerCase();
    final Color bg;
    if (s == 'live') {
      bg = const Color(0xFF1B5E20);
    } else if (s == 'simulated') {
      bg = const Color(0xFF6A1B9A);
    } else {
      bg = const Color(0xFF455A64);
    }
    return Container(
      padding: EdgeInsets.symmetric(
          horizontal: large ? 12 : 8, vertical: large ? 6 : 2),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        l.source(source),
        style: TextStyle(
          color: Colors.white,
          fontWeight: FontWeight.bold,
          fontSize: large ? 18 : 11,
          letterSpacing: 1,
        ),
      ),
    );
  }
}
