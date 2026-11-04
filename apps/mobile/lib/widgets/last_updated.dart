import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/app_settings.dart';

/// "Updated 3 min ago" line with an offline marker when the last request
/// failed and the screen shows cached data.
class LastUpdatedLabel extends StatelessWidget {
  const LastUpdatedLabel({
    super.key,
    required this.updatedAt,
    required this.offline,
    this.color,
    this.fontSize = 12,
  });

  final DateTime? updatedAt;
  final bool offline;
  final Color? color;
  final double fontSize;

  @override
  Widget build(BuildContext context) {
    final l = context.watch<AppSettings>().l10n;
    final c = color ?? Theme.of(context).colorScheme.onSurfaceVariant;
    final text = updatedAt == null
        ? l.t('never_updated')
        : l.t('last_updated', {'age': l.age(DateTime.now().difference(updatedAt!))});
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (offline) ...[
          Icon(Icons.cloud_off, size: fontSize + 2, color: Colors.orange),
          const SizedBox(width: 4),
          Text(l.t('offline_cached'),
              style: TextStyle(color: Colors.orange, fontSize: fontSize)),
          const SizedBox(width: 8),
        ],
        Text(text, style: TextStyle(color: c, fontSize: fontSize)),
      ],
    );
  }
}
