import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/api_client.dart';
import '../core/api_exceptions.dart';
import '../core/format.dart';
import '../core/json_utils.dart';
import '../models/station.dart';
import '../models/vehicle.dart';
import '../state/app_settings.dart';
import '../widgets/error_banner.dart';

/// `GET /stations` -> `GET /queue/{station}/slots` -> `POST /queue/{station}/appointments`.
class BookSlotScreen extends StatefulWidget {
  const BookSlotScreen({super.key, required this.vehicle});
  final Vehicle vehicle;

  @override
  State<BookSlotScreen> createState() => _BookSlotScreenState();
}

class _BookSlotScreenState extends State<BookSlotScreen> {
  List<Station> _stations = [];
  Station? _station;
  List<Slot> _slots = [];
  bool _loading = true;
  bool _booking = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadStations();
  }

  Future<void> _loadStations() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final list = asMapList(await context.read<ApiClient>().get('/stations'));
      if (!mounted) return;
      _stations = list.map(Station.fromJson).toList();
      _station ??= _stations.isEmpty ? null : _stations.first;
      if (_station != null) await _loadSlots();
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.detail);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadSlots() async {
    final st = _station;
    if (st == null) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final list = asMapList(
          await context.read<ApiClient>().get('/queue/${st.id}/slots'));
      if (mounted) setState(() => _slots = list.map(Slot.fromJson).toList());
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.detail);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _book(Slot s) async {
    final st = _station;
    if (st == null) return;
    final l = context.read<AppSettings>().l10n;
    setState(() {
      _booking = true;
      _error = null;
    });
    try {
      await context.read<ApiClient>().post('/queue/${st.id}/appointments', body: {
        'vehicle_id': widget.vehicle.id,
        'slot_start': s.slotStart.toIso8601String(),
      });
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(
              '${l.t('slot_booked_ok')}: ${st.code} ${fmtLocal(s.slotStart)}')));
      Navigator.of(context).pop();
    } on ApiException catch (e) {
      // 409 = slot full / vehicle already booked; 422 = alignment etc.
      if (mounted) setState(() => _error = e.detail);
      await _loadSlots();
    } finally {
      if (mounted) setState(() => _booking = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = context.watch<AppSettings>().l10n;
    return Scaffold(
      appBar: AppBar(title: Text('${l.t('book_slot')} - ${widget.vehicle.plate}')),
      body: Column(
        children: [
          if (_error != null) ErrorBanner(_error!, onRetry: _loadSlots),
          Padding(
            padding: const EdgeInsets.all(16),
            child: DropdownButtonFormField<String>(
              value: _station?.id,
              decoration: InputDecoration(labelText: l.t('stations')),
              items: _stations
                  .map((s) => DropdownMenuItem(
                        value: s.id,
                        child: Text(
                            '${s.code} - ${s.name} (${l.t('trucks_waiting', {'n': s.queueLen})})'),
                      ))
                  .toList(),
              onChanged: (id) {
                setState(() => _station =
                    _stations.cast<Station?>().firstWhere((s) => s!.id == id, orElse: () => null));
                _loadSlots();
              },
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Align(
                alignment: Alignment.centerLeft,
                child: Text(l.t('slots'),
                    style: Theme.of(context).textTheme.titleMedium)),
          ),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : ListView.builder(
                    itemCount: _slots.length,
                    itemBuilder: (ctx, i) {
                      final s = _slots[i];
                      final full = s.available <= 0;
                      return ListTile(
                        enabled: !full && !_booking,
                        leading: Icon(full ? Icons.block : Icons.schedule),
                        title: Text(
                            '${fmtLocal(s.slotStart)} - ${fmtLocal(s.slotEnd, withDate: false)}'),
                        subtitle: Text(full
                            ? l.t('full')
                            : l.t('capacity', {'a': s.available, 'c': s.capacity})),
                        trailing: full
                            ? null
                            : FilledButton(
                                onPressed: _booking ? null : () => _book(s),
                                child: Text(l.t('book_slot'))),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}
