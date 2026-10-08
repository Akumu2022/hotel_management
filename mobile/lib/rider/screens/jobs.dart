import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';
import '../../api.dart';
import '../../i18n.dart';
import '../../util.dart';
import '../location.dart';
import '../logic.dart';
import '../session.dart';

/// Go online, take a job, follow the steps, and prove the delivery with the customer's 4-digit code.
class JobsTab extends StatefulWidget {
  const JobsTab({super.key});
  @override
  State<JobsTab> createState() => _JobsTabState();
}

class _JobsTabState extends State<JobsTab> {
  late final RiderSession _s = context.read<RiderSession>();
  late final LocationReporter _gps = LocationReporter(_s);
  List<Json> _jobs = [];
  bool _loaded = false, _togglingOnline = false;
  String? _error;
  Timer? _poll;
  final _busy = <String>{};
  int _openSeen = 0;

  bool get _online => _s.me?['is_online'] == true;

  @override
  void initState() {
    super.initState();
    _load();
    _poll = Timer.periodic(const Duration(seconds: 8), (_) => _load());
    if (_online) {
      _gps.start().then((problem) {
        if (problem != null && mounted) toast(context, tr(problem));
      });
    }
  }

  @override
  void dispose() {
    _poll?.cancel();
    _gps.stop();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final r = (await _s.call('GET', '/rider/jobs') as List).cast<Json>();
      if (!mounted) return;
      final open = r.where((j) => j['mine'] != true).length;
      final hasMine = r.any((j) => j['mine'] == true);
      if (_online && !hasMine && open > _openSeen) HapticFeedback.heavyImpact(); // a new job to take
      _openSeen = open;
      _gps.onTheRoad = onTheRoad(r);
      setState(() {
        _jobs = r;
        _loaded = true;
        _error = null;
      });
    } on ApiError catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  Future<void> _toggle() async {
    setState(() => _togglingOnline = true);
    try {
      if (!_online) {
        final problem = await _gps.start();
        if (problem != null) {
          if (mounted) toast(context, tr(problem));
          return;
        }
      }
      await _s.setOnline(!_online);
      if (!_online) await _gps.stop();
      await _load();
    } on ApiError catch (e) {
      if (mounted) toast(context, e.message);
      if (!_online) await _gps.stop();
    } finally {
      if (mounted) setState(() => _togglingOnline = false);
    }
  }

  /// One step of a job (take it, picked up, delivered...). Shows the server's reason if it refuses.
  Future<bool> _run(String id, String action, {Object? body}) async {
    setState(() => _busy.add(id));
    try {
      await _s.call('POST', '/rider/jobs/$id/$action', body: body ?? {});
      HapticFeedback.mediumImpact();
      await _load();
      return true;
    } on ApiError catch (e) {
      if (mounted) toast(context, e.message);
      await _load();
      return false;
    } finally {
      if (mounted) setState(() => _busy.remove(id));
    }
  }

  @override
  Widget build(BuildContext context) {
    final mine = _jobs.where((j) => j['mine'] == true).toList();
    final open = _jobs.where((j) => j['mine'] != true).toList();
    return RefreshIndicator(
      color: brand,
      onRefresh: _load,
      child: ListView(padding: const EdgeInsets.all(16), children: [
        _OnlineCard(online: _online, busy: _togglingOnline, onTap: _toggle),
        if (_online)
          Padding(
            padding: const EdgeInsets.only(top: 8, left: 4),
            child: Row(children: [
              const Icon(Icons.location_on, size: 14, color: Color(0xFF16A34A)),
              const SizedBox(width: 4),
              Text(tr("Sharing your location with dispatch while you're online."), style: labelOf(context).copyWith(fontSize: 12)),
            ]),
          ),
        if (_error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_error!, style: const TextStyle(color: Colors.red, fontWeight: FontWeight.w600))),
        if (!_loaded && _error == null) const Padding(padding: EdgeInsets.only(top: 16), child: Skel(160)),
        for (final j in mine) ...[
          const SizedBox(height: 16),
          Text(tr('Your delivery'), style: kSection),
          const SizedBox(height: 8),
          _JobCard(job: j, busy: _busy.contains(j['id']), run: (a, {body}) => _run('${j['id']}', a, body: body)),
        ],
        if (mine.isEmpty && _loaded) ...[
          const SizedBox(height: 16),
          Text(tr('Open jobs'), style: kSection),
          const SizedBox(height: 8),
          if (!_online)
            _Empty(emoji: '🛵', text: tr('Go online to see and take jobs.'))
          else if (open.isEmpty)
            _Empty(emoji: '⏳', text: tr('No jobs right now. New ones appear here and your phone will buzz.'))
          else
            for (final j in open) Padding(padding: const EdgeInsets.only(bottom: 12), child: _JobCard(job: j, busy: _busy.contains(j['id']), run: (a, {body}) => _run('${j['id']}', a, body: body))),
        ],
        const SizedBox(height: 24),
      ]),
    );
  }
}

class _Empty extends StatelessWidget {
  final String emoji, text;
  const _Empty({required this.emoji, required this.text});
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(vertical: 32, horizontal: 20),
        decoration: BoxDecoration(border: Border.all(color: Theme.of(context).colorScheme.outlineVariant), borderRadius: BorderRadius.circular(20)),
        child: Column(children: [Text(emoji, style: const TextStyle(fontSize: 40)), const SizedBox(height: 8), Text(text, textAlign: TextAlign.center, style: TextStyle(color: mutedOf(context)))]),
      );
}

class _OnlineCard extends StatelessWidget {
  final bool online, busy;
  final VoidCallback onTap;
  const _OnlineCard({required this.online, required this.busy, required this.onTap});
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final fg = online ? Colors.white : cs.onSurface;
    return Material(
      color: online ? const Color(0xFF16A34A) : cs.surface,
      borderRadius: BorderRadius.circular(24),
      child: InkWell(
        borderRadius: BorderRadius.circular(24),
        onTap: busy ? null : onTap,
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Row(children: [
            Container(
              width: 54,
              height: 54,
              decoration: BoxDecoration(color: online ? Colors.white24 : cs.surfaceContainerHighest, borderRadius: BorderRadius.circular(16)),
              child: busy ? const Padding(padding: EdgeInsets.all(16), child: CircularProgressIndicator(strokeWidth: 2.5)) : Icon(Icons.power_settings_new, color: fg, size: 28),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(online ? tr("You're online") : tr("You're offline"), style: kTitle.copyWith(color: fg)),
                Text(online ? tr('New jobs appear below. Tap to go offline.') : tr('Tap to go online and start taking jobs.'), style: TextStyle(color: online ? Colors.white70 : mutedOf(context), fontSize: 13)),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}

class _JobCard extends StatefulWidget {
  final Json job;
  final bool busy;
  final Future<bool> Function(String action, {Object? body}) run;
  const _JobCard({required this.job, required this.busy, required this.run});
  @override
  State<_JobCard> createState() => _JobCardState();
}

class _JobCardState extends State<_JobCard> {
  final _code = TextEditingController();

  Json get j => widget.job;

  Future<bool?> _ask(String title, String body, {String yes = 'Yes', String no = 'No'}) => showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text(title),
          content: Text(body),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(tr(no))),
            FilledButton(style: FilledButton.styleFrom(minimumSize: const Size(88, 44)), onPressed: () => Navigator.pop(ctx, true), child: Text(tr(yes))),
          ],
        ),
      );

  Future<void> _openMap(double? lat, double? lng) async {
    if (lat == null || lng == null) return toast(context, tr('No map location for this stop'));
    await launchUrl(directionsTo(lat, lng), mode: LaunchMode.externalApplication);
  }

  Future<void> _pickedUp() async {
    if (j['fee_with_food'] == true && j['fee_rider_confirmed'] != true) {
      final got = await _ask(tr('Delivery fee'), tr('Did the hotel give you the delivery fee {amount} with the food?', {'amount': kes(j['rider_fee'])}), yes: 'Yes, I got it', no: 'No');
      if (got == null) return;
      await widget.run('picked-up', body: {'fee_received': got});
    } else {
      await widget.run('picked-up');
    }
  }

  Future<void> _delivered() async {
    final code = _code.text.trim();
    if (!RegExp(r'^\d{4}$').hasMatch(code)) return toast(context, tr("Enter the customer's 4-digit code"));
    Map<String, dynamic> body = {'code': code};
    if (j['collect_cash_fee'] == true) {
      final got = await _ask(tr('Cash delivery fee'), tr('Did you collect {amount} cash from the customer?', {'amount': kes(j['rider_fee'])}), yes: 'Yes, I got the cash', no: 'No');
      if (got == null) return;
      body['cash_fee_received'] = got;
    }
    if (await widget.run('delivered', body: body)) {
      _code.clear();
      // No cash from the customer: tell Chakula, who ask the customer and pay the rider in the weekly payout.
      if (body['cash_fee_received'] == false) await widget.run('fee-not-paid');
    }
  }

  Future<void> _cannotDeliver() async {
    final reason = await showModalBottomSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Padding(padding: const EdgeInsets.all(16), child: Text(tr("Why can't you deliver?"), style: kSection)),
          for (final e in failReasons.entries) ListTile(title: Text(tr(e.value)), onTap: () => Navigator.pop(ctx, e.key)),
        ]),
      ),
    );
    if (reason != null) await widget.run('failed', body: {'reason': reason});
  }

  String _readyText() {
    if (j['status'] == 'ready') return tr('Food is ready');
    final prep = j['prep_minutes'];
    final at = j['accepted_at'] == null ? null : DateTime.tryParse('${j['accepted_at']}');
    if (prep is int && at != null) {
      final left = at.add(Duration(minutes: prep)).difference(DateTime.now()).inMinutes;
      return left > 0 ? tr('Ready in about {n} min', {'n': left}) : tr('Should be ready any moment');
    }
    return tr('Being prepared');
  }

  @override
  Widget build(BuildContext context) {
    final stage = jobStage(j);
    final mine = stage != JobStage.open;
    final cs = Theme.of(context).colorScheme;
    final busy = widget.busy;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text('${j['hotel_name']}', style: kTitle)),
            Text(kes(j['rider_fee']), style: kTitle.copyWith(color: brand)),
          ]),
          const SizedBox(height: 6),
          Wrap(spacing: 6, runSpacing: 6, children: [
            if (j['distance_km'] != null) Pill('${j['distance_km']} km', icon: Icons.route_outlined),
            if (j['collect_cash_fee'] == true) Pill(tr('Collect cash fee'), icon: Icons.payments_outlined, bg: const Color(0xFFFEF3C7), fg: const Color(0xFF92400E)),
            if (j['fee_with_food'] == true) Pill(tr('Fee comes with the food'), icon: Icons.redeem_outlined, bg: const Color(0xFFDCFCE7), fg: const Color(0xFF15803D)),
            if (stage == JobStage.toHotel || stage == JobStage.readyAtHotel) Pill(_readyText(), icon: Icons.restaurant_outlined),
          ]),
          const SizedBox(height: 10),
          for (final i in (j['items'] as List)) Text('$i', style: kBody),
          if (!mine) const SizedBox(height: 14),
          if (mine) ...[
            const SizedBox(height: 14),
            TweenAnimationBuilder<double>(
              tween: Tween(end: jobStep(stage) / 4),
              duration: const Duration(milliseconds: 500),
              builder: (_, v, __) => ClipRRect(borderRadius: BorderRadius.circular(99), child: LinearProgressIndicator(value: v, minHeight: 8, backgroundColor: cs.surfaceContainerHighest)),
            ),
            const SizedBox(height: 6),
            Text(switch (stage) {
              JobStage.toHotel => tr('Go to the hotel'),
              JobStage.readyAtHotel => tr('Collect the food'),
              JobStage.toCustomer => tr('Food collected: head to the customer'),
              _ => tr('On the way to the customer'),
            }, style: labelOf(context)),
            const SizedBox(height: 12),
          ],
          if (stage == JobStage.open)
            FilledButton(
              style: fullWidthFilled,
              onPressed: busy ? null : () => widget.run('claim'),
              child: busy ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : Text(tr('Take this job')),
            ),
          if (stage == JobStage.toHotel || stage == JobStage.readyAtHotel) ...[
            OutlinedButton.icon(onPressed: () => _openMap((j['hotel_lat'] as num?)?.toDouble(), (j['hotel_lng'] as num?)?.toDouble()), icon: const Icon(Icons.navigation_outlined, size: 20), label: Text(tr('Directions to the hotel'))),
            const SizedBox(height: 8),
            ContactRow(j['hotel_phone'] as String?, message: "Hello ${j['hotel_name']}, I'm the Chakula rider for order #${j['code']}."),
            const SizedBox(height: 12),
            FilledButton(
              style: fullWidthFilled,
              onPressed: busy || stage != JobStage.readyAtHotel ? null : _pickedUp,
              child: busy ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : Text(stage == JobStage.readyAtHotel ? tr('I have the food') : tr('Wait for the food')),
            ),
            TextButton(
              onPressed: busy
                  ? null
                  : () async {
                      final ok = await _ask(tr('Release this job?'), tr('Another rider will take it. Only do this if you cannot do it.'), yes: 'Release', no: 'Keep it');
                      if (ok == true) await widget.run('release');
                    },
              child: Text(tr('Release this job')),
            ),
          ],
          if (stage == JobStage.toCustomer || stage == JobStage.atDoor) ...[
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: cs.surfaceContainerHighest, borderRadius: BorderRadius.circular(14)),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${j['customer_name'] ?? ''}', style: kItem),
                if (j['landmark'] != null) Text('${j['landmark']}', style: kBody),
              ]),
            ),
            const SizedBox(height: 8),
            OutlinedButton.icon(onPressed: () => _openMap((j['lat'] as num?)?.toDouble(), (j['lng'] as num?)?.toDouble()), icon: const Icon(Icons.navigation_outlined, size: 20), label: Text(tr('Directions to the customer'))),
            const SizedBox(height: 8),
            ContactRow(j['customer_phone'] as String?, message: "Hi ${j['customer_name'] ?? ''}, I'm your Chakula rider for order #${j['code']}."),
            const SizedBox(height: 12),
            if (stage == JobStage.toCustomer)
              FilledButton.tonal(
                style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
                onPressed: busy ? null : () => widget.run('on-the-way'),
                child: Text(tr("I'm on my way")),
              ),
            const SizedBox(height: 14),
            Text(tr("Ask the customer for their 4-digit code"), style: kSection),
            const SizedBox(height: 8),
            TextField(
              controller: _code,
              keyboardType: TextInputType.number,
              maxLength: 4,
              textAlign: TextAlign.center,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w900, letterSpacing: 10),
              decoration: InputDecoration(counterText: '', hintText: '0000', helperText: j['code_attempts_left'] == null ? null : tr('{n} tries left', {'n': j['code_attempts_left']})),
            ),
            const SizedBox(height: 10),
            FilledButton(
              style: fullWidthFilled.merge(FilledButton.styleFrom(backgroundColor: const Color(0xFF16A34A))),
              onPressed: busy ? null : _delivered,
              child: busy ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : Text(tr('Delivered')),
            ),
            TextButton(onPressed: busy ? null : _cannotDeliver, child: Text(tr("I can't deliver this order"))),
          ],
        ]),
      ),
    );
  }
}
