import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../api.dart';
import '../../i18n.dart';
import '../../store.dart';
import '../../util.dart';
import '../logic.dart';
import '../session.dart';
import 'auth.dart';
import 'jobs.dart';
import 'status.dart';
import 'wallet.dart';

/// The approved rider's app: Jobs, History and Profile with a bottom bar.
class RiderHome extends StatefulWidget {
  const RiderHome({super.key});
  @override
  State<RiderHome> createState() => _RiderHomeState();
}

class _RiderHomeState extends State<RiderHome> {
  int _tab = 0;
  Json? _wallet; // set only when the payments module is on: adds the Wallet tab

  @override
  void initState() {
    super.initState();
    _loadWallet();
  }

  Future<void> _loadWallet() async {
    try {
      final w = await context.read<RiderSession>().call('GET', '/rider/wallet') as Json;
      if (mounted && w['enabled'] == true) setState(() => _wallet = w);
    } catch (_) {
      // No wallet is fine: the app works exactly as before.
    }
  }

  @override
  Widget build(BuildContext context) {
    final me = context.watch<RiderSession>().me ?? {};
    final first = '${me['name'] ?? ''}'.split(' ').first;
    final hasWallet = _wallet != null;
    final profile = hasWallet ? 3 : 2;
    final title = _tab == 0
        ? (first.isEmpty ? 'Chakula Rider' : tr('Hi {name}', {'name': first}))
        : _tab == 1
            ? tr('History')
            : _tab == profile
                ? tr('Profile')
                : tr('Wallet');
    return Scaffold(
      appBar: AppBar(
        title: Text(title, style: kTitle),
        actions: [
          Padding(padding: const EdgeInsets.only(right: 12), child: langSwitch()),
        ],
      ),
      body: IndexedStack(index: _tab, children: [
        const JobsTab(),
        _tab == 1 ? const HistoryTab() : const SizedBox.shrink(),
        if (hasWallet) WalletTab(initial: _wallet!),
        const ProfileTab(),
      ]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        height: 66,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: [
          NavigationDestination(icon: const Icon(Icons.two_wheeler_outlined), selectedIcon: const Icon(Icons.two_wheeler, color: brand), label: tr('Jobs')),
          NavigationDestination(icon: const Icon(Icons.receipt_long_outlined), selectedIcon: const Icon(Icons.receipt_long, color: brand), label: tr('History')),
          if (hasWallet) NavigationDestination(icon: const Icon(Icons.account_balance_wallet_outlined), selectedIcon: const Icon(Icons.account_balance_wallet, color: brand), label: tr('Wallet')),
          NavigationDestination(icon: const Icon(Icons.person_outline), selectedIcon: const Icon(Icons.person, color: brand), label: tr('Profile')),
        ],
      ),
    );
  }
}

/// Finished deliveries and what was earned today.
class HistoryTab extends StatefulWidget {
  const HistoryTab({super.key});
  @override
  State<HistoryTab> createState() => _HistoryTabState();
}

class _HistoryTabState extends State<HistoryTab> {
  late Future<List<Json>> _rows = _load();
  Future<List<Json>> _load() async => (await context.read<RiderSession>().call('GET', '/rider/jobs/history') as List).cast<Json>();

  @override
  Widget build(BuildContext context) => RefreshIndicator(
        color: brand,
        onRefresh: () async {
          setState(() => _rows = _load());
          await _rows;
        },
        child: FutureBuilder<List<Json>>(
          future: _rows,
          builder: (_, snap) {
            if (snap.connectionState != ConnectionState.done) return ListView(padding: const EdgeInsets.all(16), children: const [Skel(90), SizedBox(height: 12), Skel(70), SizedBox(height: 12), Skel(70)]);
            if (snap.hasError) return ListView(children: [const SizedBox(height: 100), Center(child: Text('${snap.error}'))]);
            final rows = snap.data!;
            final today = earnedToday(rows, DateTime.now());
            return ListView(padding: const EdgeInsets.all(16), children: [
              Container(
                padding: const EdgeInsets.all(18),
                decoration: BoxDecoration(color: brand, borderRadius: BorderRadius.circular(22)),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(tr('Earned today'), style: const TextStyle(color: Colors.white70, fontWeight: FontWeight.w600)),
                  Text(kes(today), style: const TextStyle(color: Colors.white, fontSize: 32, fontWeight: FontWeight.w900)),
                ]),
              ),
              const SizedBox(height: 16),
              if (rows.isEmpty) Padding(padding: const EdgeInsets.all(32), child: Center(child: Text(tr('No finished deliveries yet.'), style: TextStyle(color: mutedOf(context))))),
              for (final j in rows)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: Card(
                    child: ListTile(
                      title: Text('${j['hotel_name']} · #${j['code']}', style: kItem),
                      subtitle: Text((j['items'] as List).join(', '), maxLines: 2, overflow: TextOverflow.ellipsis),
                      trailing: j['status'] == 'delivered' ? Text(kes(j['rider_fee']), style: const TextStyle(color: Color(0xFF16A34A), fontWeight: FontWeight.w800)) : Text(tr('Failed'), style: const TextStyle(color: Colors.red, fontWeight: FontWeight.w800)),
                    ),
                  ),
                ),
            ]);
          },
        ),
      );
}

/// Who you are, your bike, language and sign out.
class ProfileTab extends StatelessWidget {
  const ProfileTab({super.key});
  @override
  Widget build(BuildContext context) {
    final s = context.watch<RiderSession>();
    final me = s.me ?? {};
    final dark = Theme.of(context).brightness == Brightness.dark;
    Widget row(String k, String v) => ListTile(dense: true, title: Text(k, style: labelOf(context)), subtitle: Text(v, style: kItem));
    return ListView(padding: const EdgeInsets.all(16), children: [
      Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(children: [
            CircleAvatar(
              radius: 32,
              backgroundColor: const Color(0xFFFFE4D6),
              backgroundImage: me['photo_url'] == null ? null : NetworkImage(absUrl('${me['photo_url']}')),
              child: me['photo_url'] == null ? const Icon(Icons.person, size: 32, color: brand) : null,
            ),
            const SizedBox(width: 14),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${me['name'] ?? ''}', style: kTitle),
              Text('${me['phone'] ?? ''}', style: labelOf(context)),
              if (me['rating'] != null) Padding(padding: const EdgeInsets.only(top: 4), child: Pill('${(me['rating'] as num).toStringAsFixed(1)} (${me['rating_count']})', icon: Icons.star_rounded)),
            ])),
          ]),
        ),
      ),
      const SizedBox(height: 12),
      Card(child: Column(children: [
        row(tr('Bike number plate'), '${me['bike_plate'] ?? tr('Not added')}'),
        row(tr('Bike'), '${me['bike_description'] ?? tr('Not added')}'),
        row(tr('Lives in'), '${me['residence_area'] ?? ''}'),
        row(tr('Next of kin'), '${me['next_of_kin'] ?? ''}'),
      ])),
      const SizedBox(height: 12),
      Card(child: Column(children: [
        ListTile(leading: const Icon(Icons.translate), title: Text(tr('Language')), trailing: langSwitch()),
        SwitchListTile(
          secondary: Icon(dark ? Icons.dark_mode : Icons.dark_mode_outlined),
          title: Text(tr('Dark mode')),
          value: dark,
          onChanged: (v) => context.read<AppState>().setTheme(v ? ThemeMode.dark : ThemeMode.light),
        ),
        ListTile(leading: const Icon(Icons.lock_outline), title: Text(tr('Change password')), trailing: const Icon(Icons.chevron_right), onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ChangePasswordScreen()))),
        ListTile(
          leading: const Icon(Icons.support_agent_outlined),
          title: Text(tr('Help on WhatsApp')),
          onTap: () => openWhatsApp(context, 'Hello Chakula, I am a rider and I need help with '),
        ),
      ])),
      const SizedBox(height: 16),
      OutlinedButton.icon(onPressed: s.signOut, icon: const Icon(Icons.logout), label: Text(tr('Sign out'))),
    ]);
  }
}
