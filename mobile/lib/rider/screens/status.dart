import 'dart:async';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../api.dart';
import '../../i18n.dart';
import '../../util.dart';
import '../logic.dart';
import '../session.dart';
import 'apply.dart';
import 'auth.dart';

/// A centred message page used for "waiting", "rejected" and "suspended".
class _Notice extends StatelessWidget {
  final String emoji, title, body;
  final List<Widget> actions;
  const _Notice({required this.emoji, required this.title, required this.body, required this.actions});

  @override
  Widget build(BuildContext context) => Scaffold(
        body: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(children: [
              Align(alignment: Alignment.centerRight, child: langSwitch()),
              const Spacer(),
              Text(emoji, style: const TextStyle(fontSize: 64)),
              const SizedBox(height: 12),
              Text(title, textAlign: TextAlign.center, style: kTitle.copyWith(fontSize: 24)),
              const SizedBox(height: 10),
              Text(body, textAlign: TextAlign.center, style: TextStyle(color: mutedOf(context), fontSize: 15)),
              const Spacer(),
              ...actions,
            ]),
          ),
        ),
      );
}

/// The application is with the Chakula team. Checks for the decision every 20 seconds.
class PendingScreen extends StatefulWidget {
  const PendingScreen({super.key});
  @override
  State<PendingScreen> createState() => _PendingScreenState();
}

class _PendingScreenState extends State<PendingScreen> {
  Timer? _t;
  @override
  void initState() {
    super.initState();
    _t = Timer.periodic(const Duration(seconds: 20), (_) => context.read<RiderSession>().loadMe().catchError((_) => <String, dynamic>{}));
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<RiderSession>();
    final me = s.me ?? {};
    return _Notice(
      emoji: '⏳',
      title: tr('Application received'),
      body: tr("The Chakula team is checking your ID and bike details. You'll be able to take jobs as soon as you're approved. This page updates by itself."),
      actions: [
        if (me['bike_plate'] != null) Padding(padding: const EdgeInsets.only(bottom: 12), child: Pill('${me['bike_plate']} · ${me['bike_description'] ?? ''}', icon: Icons.two_wheeler)),
        const LinearProgressIndicator(minHeight: 4),
        const SizedBox(height: 16),
        OutlinedButton(onPressed: () => s.loadMe().catchError((_) => <String, dynamic>{}), child: Text(tr('Check now'))),
        TextButton(onPressed: s.signOut, child: Text(tr('Sign out'))),
      ],
    );
  }
}

class SuspendedScreen extends StatelessWidget {
  const SuspendedScreen({super.key});
  @override
  Widget build(BuildContext context) {
    final s = context.watch<RiderSession>();
    return _Notice(
      emoji: '⛔',
      title: tr('Your account is paused'),
      body: '${s.me?['kyc_note'] ?? tr('Please contact the Chakula team.')}',
      actions: [
        OutlinedButton(onPressed: () => s.loadMe().catchError((_) => <String, dynamic>{}), child: Text(tr('Check again'))),
        TextButton(onPressed: s.signOut, child: Text(tr('Sign out'))),
      ],
    );
  }
}

class RejectedScreen extends StatelessWidget {
  const RejectedScreen({super.key});
  @override
  Widget build(BuildContext context) {
    final s = context.watch<RiderSession>();
    return _Notice(
      emoji: '📝',
      title: tr('Please fix your application'),
      body: s.me?['kyc_note'] == null ? tr('The team needs a few things changed before they can approve you.') : '${s.me!['kyc_note']}',
      actions: [
        FilledButton(style: fullWidthFilled, onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const FixApplicationScreen())), child: Text(tr('Fix and send again'))),
        TextButton(onPressed: s.signOut, child: Text(tr('Sign out'))),
      ],
    );
  }
}

/// Edit the details and retake photos after the team sent the application back.
class FixApplicationScreen extends StatefulWidget {
  const FixApplicationScreen({super.key});
  @override
  State<FixApplicationScreen> createState() => _FixApplicationScreenState();
}

class _FixApplicationScreenState extends State<FixApplicationScreen> {
  late final Map<String, TextEditingController> _c;
  final _newPhotos = <String, Uint8List>{};
  bool _busy = false, _consent = false;
  Map<String, String> _errors = {};
  String? _formError;

  @override
  void initState() {
    super.initState();
    final me = context.read<RiderSession>().me ?? {};
    String v(String k) => '${me[k] ?? ''}';
    _c = {
      'name': TextEditingController(text: v('name')),
      'national_id': TextEditingController(text: v('national_id')),
      'phone': TextEditingController(text: v('phone')),
      'residence_area': TextEditingController(text: v('residence_area')),
      'bike_plate': TextEditingController(text: v('bike_plate')),
      'bike_description': TextEditingController(text: v('bike_description')),
      'next_of_kin': TextEditingController(text: v('next_of_kin')),
      'next_of_kin_phone': TextEditingController(text: v('next_of_kin_phone')),
    };
  }

  Future<void> _send() async {
    final a = Applicant()
      ..name = _c['name']!.text
      ..nationalId = _c['national_id']!.text
      ..phone = _c['phone']!.text.isEmpty ? '0700000000' : _c['phone']!.text
      ..residence = _c['residence_area']!.text
      ..bikePlate = _c['bike_plate']!.text
      ..bikeDescription = _c['bike_description']!.text
      ..kin = _c['next_of_kin']!.text
      ..kinPhone = _c['next_of_kin_phone']!.text;
    final e = checkApplicant(a, needPassword: false)..remove('phone'); // the login phone can't be changed here
    setState(() => _errors = e);
    if (e.isNotEmpty) return;
    if (!_consent) {
      setState(() => _formError = tr('Tick the box to agree to the ID check.'));
      return;
    }
    setState(() {
      _busy = true;
      _formError = null;
    });
    final s = context.read<RiderSession>();
    try {
      await s.call('PATCH', '/rider/me', body: {
        'name': a.name.trim(),
        'national_id': a.nationalId.trim(),
        'residence_area': a.residence.trim(),
        'bike_plate': tidyPlate(a.bikePlate),
        'bike_description': a.bikeDescription.trim(),
        'next_of_kin': a.kin.trim(),
        'next_of_kin_phone': kenyanNumber(a.kinPhone),
      });
      for (final p in _newPhotos.entries) {
        await s.upload('/rider/kyc/${p.key}', {'file': p.value});
      }
      await s.call('POST', '/rider/submit', body: {'consent': true});
      await s.loadMe();
      if (mounted) Navigator.of(context).popUntil((r) => r.isFirst);
    } on ApiError catch (e) {
      if (mounted) setState(() => _formError = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _f(String k, String label, {TextInputType? type, TextCapitalization caps = TextCapitalization.none}) => Padding(
        padding: const EdgeInsets.only(bottom: 14),
        child: TextField(controller: _c[k], keyboardType: type, textCapitalization: caps, decoration: InputDecoration(labelText: label, errorText: _errors[k] == null ? null : tr(_errors[k]!), errorMaxLines: 3)),
      );

  Future<void> _retake(String kind) async {
    final b = await pickPhoto(context, selfie: kind == 'selfie');
    if (b != null && mounted) setState(() => _newPhotos[kind] = b);
  }

  @override
  Widget build(BuildContext context) {
    const kinds = {
      'id_front': ('ID front', Icons.badge_outlined),
      'id_back': ('ID back', Icons.badge_outlined),
      'selfie': ('Selfie', Icons.face_outlined),
      'logbook': ('Bike logbook (optional)', Icons.description_outlined),
    };
    return Scaffold(
      appBar: AppBar(title: Text(tr('Fix your application'), style: kSection)),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        if (_formError != null) Container(width: double.infinity, margin: const EdgeInsets.only(bottom: 12), padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: const Color(0xFFFEE2E2), borderRadius: BorderRadius.circular(12)), child: Text(_formError!, style: const TextStyle(color: Color(0xFFB91C1C), fontWeight: FontWeight.w700))),
        _f('name', tr('Full name (as on your ID)'), caps: TextCapitalization.words),
        _f('national_id', tr('ID number'), type: TextInputType.number),
        _f('residence_area', tr('Where you live')),
        _f('bike_plate', tr('Number plate'), caps: TextCapitalization.characters),
        _f('bike_description', tr('Describe the bike')),
        _f('next_of_kin', tr('Next of kin: full name'), caps: TextCapitalization.words),
        _f('next_of_kin_phone', tr('Next of kin: phone'), type: TextInputType.phone),
        Text(tr('Photos'), style: kSection),
        const SizedBox(height: 8),
        for (final k in kinds.entries)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: PhotoSlot(
              title: tr(k.value.$1),
              hint: _newPhotos[k.key] != null ? tr('New photo ready') : (context.read<RiderSession>().me?['photos']?[k.key] == true ? tr('Already uploaded. Tap to replace it.') : tr('Not added')),
              icon: k.value.$2,
              bytes: _newPhotos[k.key],
              error: null,
              onTap: () => _retake(k.key),
            ),
          ),
        CheckboxListTile(
          contentPadding: EdgeInsets.zero,
          controlAffinity: ListTileControlAffinity.leading,
          value: _consent,
          onChanged: (v) => setState(() => _consent = v ?? false),
          title: Text(tr('I agree that Chakula keeps my ID photos, selfie and bike details to confirm who I am and to keep customers safe. Only the Chakula team can see them.'), style: kBody),
        ),
        const SizedBox(height: 12),
        FilledButton(style: fullWidthFilled, onPressed: _busy ? null : _send, child: _busy ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : Text(tr('Send again'))),
        const SizedBox(height: 24),
      ]),
    );
  }
}

/// Shown after the admin resets the password: choose your own before doing anything else.
class ChangePasswordScreen extends StatefulWidget {
  final bool required;
  const ChangePasswordScreen({super.key, this.required = false});
  @override
  State<ChangePasswordScreen> createState() => _ChangePasswordScreenState();
}

class _ChangePasswordScreenState extends State<ChangePasswordScreen> {
  final _old = TextEditingController(), _new = TextEditingController(), _again = TextEditingController();
  bool _busy = false;
  String? _error;

  Future<void> _go() async {
    if (_new.text.length < 8) return setState(() => _error = tr('Use at least 8 characters.'));
    if (_new.text != _again.text) return setState(() => _error = tr("The two new passwords don't match."));
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await context.read<RiderSession>().changePassword(_old.text, _new.text);
      if (mounted && !widget.required) {
        toast(context, tr('Password changed'));
        Navigator.pop(context);
      }
    } on ApiError catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(tr('Change password'), style: kSection), automaticallyImplyLeading: !widget.required),
        body: ListView(padding: const EdgeInsets.all(20), children: [
          if (widget.required) Padding(padding: const EdgeInsets.only(bottom: 16), child: Text(tr('The team gave you a temporary password. Choose your own to continue.'), style: kBody)),
          TextField(controller: _old, obscureText: true, decoration: InputDecoration(labelText: tr('Current password'))),
          const SizedBox(height: 14),
          TextField(controller: _new, obscureText: true, decoration: InputDecoration(labelText: tr('New password'))),
          const SizedBox(height: 14),
          TextField(controller: _again, obscureText: true, decoration: InputDecoration(labelText: tr('New password again'))),
          if (_error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_error!, style: const TextStyle(color: Colors.red, fontWeight: FontWeight.w600))),
          const SizedBox(height: 20),
          FilledButton(style: fullWidthFilled, onPressed: _busy ? null : _go, child: _busy ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : Text(tr('Save'))),
        ]),
      );
}
