import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/format.dart';
import '../state/app_settings.dart';
import '../state/cargo_state.dart';
import '../widgets/last_updated.dart';

/// `GET /notifications` inbox; tapping marks read via `POST /notifications/{id}/read`.
class NotificationsScreen extends StatelessWidget {
  const NotificationsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final l = context.watch<AppSettings>().l10n;
    final cargo = context.watch<CargoState>();
    return Scaffold(
      appBar: AppBar(
        title: Text(l.t('notifications')),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: Center(
                child: LastUpdatedLabel(
                    updatedAt: cargo.inboxUpdated, offline: cargo.offline)),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: cargo.loadInbox,
        child: cargo.notifications.isEmpty
            ? ListView(children: [
                Padding(
                  padding: const EdgeInsets.all(32),
                  child: Center(
                      child: cargo.loadingInbox
                          ? const CircularProgressIndicator()
                          : Text(l.t('no_notifications'))),
                )
              ])
            : ListView.separated(
                itemCount: cargo.notifications.length,
                separatorBuilder: (_, __) => const Divider(height: 1),
                itemBuilder: (ctx, i) {
                  final n = cargo.notifications[i];
                  return ListTile(
                    leading: Icon(
                      n.channel == 'sms' ? Icons.sms_outlined : Icons.notifications_outlined,
                      color: n.isRead ? Theme.of(ctx).colorScheme.outline : Theme.of(ctx).colorScheme.primary,
                    ),
                    title: Text(n.title,
                        style: TextStyle(
                            fontWeight: n.isRead ? FontWeight.normal : FontWeight.bold)),
                    subtitle: Text('${n.body}\n${fmtLocal(n.createdAt)}  -  ${n.template}'),
                    isThreeLine: true,
                    onTap: n.isRead ? null : () => cargo.markRead(n),
                  );
                },
              ),
      ),
    );
  }
}
