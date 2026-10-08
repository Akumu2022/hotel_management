import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../api.dart';
import '../i18n.dart';
import '../store.dart';
import '../theme.dart';
import 'screens/auth.dart';
import 'screens/home.dart';
import 'screens/status.dart';
import 'session.dart';

/// The rider app: sign up with ID and bike details, then take and deliver jobs.
///   flutter run --flavor rider -t lib/rider/main.dart
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final state = AppState();
  await loadServerSetting();
  await state.load(); // language and dark mode
  final session = RiderSession();
  await session.init();
  runApp(MultiProvider(
    providers: [ChangeNotifierProvider.value(value: state), ChangeNotifierProvider.value(value: session)],
    child: const RiderApp(),
  ));
}

class RiderApp extends StatelessWidget {
  const RiderApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Chakula Rider',
        debugShowCheckedModeBanner: false,
        theme: appTheme(Brightness.light),
        darkTheme: appTheme(Brightness.dark),
        themeMode: context.select<AppState, ThemeMode>((s) => s.themeMode),
        builder: (context, child) => ValueListenableBuilder<String>(
          valueListenable: lang,
          builder: (_, l, __) => KeyedSubtree(
            key: ValueKey(l),
            child: MediaQuery(
              data: MediaQuery.of(context).copyWith(textScaler: MediaQuery.textScalerOf(context).clamp(maxScaleFactor: 1.25)),
              child: child!,
            ),
          ),
        ),
        home: const _Gate(),
      );
}

/// Sends the rider to the right place for where their application is.
class _Gate extends StatelessWidget {
  const _Gate();
  @override
  Widget build(BuildContext context) {
    final s = context.watch<RiderSession>();
    if (!s.signedIn || s.me == null) return const WelcomeScreen();
    if (s.mustChangePassword) return const ChangePasswordScreen(required: true);
    return switch (s.status) {
      'approved' => const RiderHome(),
      'rejected' || 'draft' => const RejectedScreen(),
      'suspended' => const SuspendedScreen(),
      _ => const PendingScreen(), // pending
    };
  }
}
