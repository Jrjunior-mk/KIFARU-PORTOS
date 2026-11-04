import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/app_settings.dart';

class ErrorBanner extends StatelessWidget {
  const ErrorBanner(this.message, {super.key, this.onRetry});

  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final l = context.watch<AppSettings>().l10n;
    final cs = Theme.of(context).colorScheme;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      color: cs.errorContainer,
      child: Row(
        children: [
          Icon(Icons.error_outline, color: cs.onErrorContainer),
          const SizedBox(width: 8),
          Expanded(
            child: Text(message, style: TextStyle(color: cs.onErrorContainer)),
          ),
          if (onRetry != null)
            TextButton(onPressed: onRetry, child: Text(l.t('retry'))),
        ],
      ),
    );
  }
}
