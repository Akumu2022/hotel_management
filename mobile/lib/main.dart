import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'screens/home.dart';
import 'store.dart';

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
        theme: ThemeData(
          colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFFE8590C)),
          useMaterial3: true,
        ),
        home: const HomeScreen(),
      );
}
