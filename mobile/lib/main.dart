import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'i18n.dart';
import 'screens/shell.dart';
import 'store.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final state = AppState();
  await state.load();
  runApp(ChangeNotifierProvider.value(value: state, child: const HotelApp()));
}

class HotelApp extends StatelessWidget {
  const HotelApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Order Food',
        debugShowCheckedModeBanner: false,
        theme: appTheme(Brightness.light),
        darkTheme: appTheme(Brightness.dark),
        themeMode: context.select<AppState, ThemeMode>((s) => s.themeMode),
        builder: (context, child) => ValueListenableBuilder<String>(
          valueListenable: lang,
          // A new key rebuilds every screen so all text switches language at once.
          builder: (_, l, __) => KeyedSubtree(
            key: ValueKey(l),
            child: MediaQuery(
              data: MediaQuery.of(context).copyWith(textScaler: MediaQuery.textScalerOf(context).clamp(maxScaleFactor: 1.25)),
              child: child!,
            ),
          ),
        ),
        home: const Shell(),
      );
}
