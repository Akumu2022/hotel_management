import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../api.dart';
import '../../i18n.dart';
import '../../store.dart';
import '../../util.dart';
import '../session.dart';
import 'apply.dart';

/// First screen for a rider who isn't signed in.
class WelcomeScreen extends StatelessWidget {
  const WelcomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Align(alignment: Alignment.centerRight, child: _LangSwitch()),
            const Spacer(),
            Align(
              alignment: Alignment.centerLeft,
              child: Container(
                width: 84,
                height: 84,
                decoration: BoxDecoration(color: brand, borderRadius: BorderRadius.circular(26)),
                child: const Icon(Icons.two_wheeler, color: Colors.white, size: 46),
              ),
            ),
            const SizedBox(height: 24),
            Text('Chakula Rider', style: kTitle.copyWith(fontSize: 30)),
            const SizedBox(height: 8),
            Text(tr('Deliver food around town and get paid for every trip.'), style: TextStyle(color: mutedOf(context), fontSize: 16)),
            const Spacer(),
            FilledButton(
              style: fullWidthFilled,
              onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const SignInScreen())),
              child: Text(tr('Sign in')),
            ),
            const SizedBox(height: 12),
            OutlinedButton(
              onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ApplyScreen())),
              child: Text(tr('Apply to ride')),
            ),
            const SizedBox(height: 16),
            Text(tr('Applications are checked by the Chakula team before you can take jobs.'), textAlign: TextAlign.center, style: TextStyle(color: cs.onSurfaceVariant, fontSize: 13)),
          ]),
        ),
      ),
    );
  }
}

class SignInScreen extends StatefulWidget {
  const SignInScreen({super.key});
  @override
  State<SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends State<SignInScreen> {
  final _phone = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false, _hide = true;
  String? _error;

  Future<void> _go() async {
    if (_phone.text.trim().isEmpty || _password.text.isEmpty) {
      setState(() => _error = tr('Enter your phone number and password'));
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await context.read<RiderSession>().signIn(_phone.text.trim(), _password.text);
      if (mounted) Navigator.of(context).popUntil((r) => r.isFirst);
    } on ApiError catch (e) {
      if (mounted) setState(() => _error = e.status == 401 ? tr('Wrong phone number or password') : e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(tr('Sign in'), style: kSection)),
        body: ListView(padding: const EdgeInsets.all(20), children: [
          TextField(controller: _phone, keyboardType: TextInputType.phone, autofillHints: const [AutofillHints.telephoneNumber], decoration: InputDecoration(labelText: tr('Phone number'), hintText: '0712 345 678')),
          const SizedBox(height: 14),
          TextField(
            controller: _password,
            obscureText: _hide,
            onSubmitted: (_) => _go(),
            decoration: InputDecoration(labelText: tr('Password'), suffixIcon: IconButton(icon: Icon(_hide ? Icons.visibility_off_outlined : Icons.visibility_outlined), onPressed: () => setState(() => _hide = !_hide))),
          ),
          if (_error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_error!, style: const TextStyle(color: Colors.red, fontWeight: FontWeight.w600))),
          const SizedBox(height: 20),
          FilledButton(
            style: fullWidthFilled,
            onPressed: _busy ? null : _go,
            child: _busy ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : Text(tr('Sign in')),
          ),
          const SizedBox(height: 12),
          TextButton(
            onPressed: () => Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => const ApplyScreen())),
            child: Text(tr('New here? Apply to ride')),
          ),
        ]),
      );
}

/// EN | SW switch (same as the customer app).
class _LangSwitch extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    Widget chip(String code, String label) {
      final on = lang.value == code;
      return GestureDetector(
        onTap: () => context.read<AppState>().setLang(code),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
          decoration: BoxDecoration(color: on ? brand : Colors.transparent, borderRadius: BorderRadius.circular(99)),
          child: Text(label, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: on ? Colors.white : cs.onSurface)),
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(color: cs.surfaceContainerHighest, borderRadius: BorderRadius.circular(99), border: Border.all(color: cs.outlineVariant)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [chip('en', 'EN'), chip('sw', 'SW')]),
    );
  }
}

/// Language switch for rider screens.
Widget langSwitch() => _LangSwitch();
