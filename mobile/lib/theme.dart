import 'package:flutter/material.dart';

import 'util.dart';

OutlineInputBorder _border(Color c, [double w = 1]) =>
    OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: BorderSide(color: c, width: w));

ThemeData appTheme(Brightness b) {
  final dark = b == Brightness.dark;
  final scheme = ColorScheme.fromSeed(seedColor: brand, brightness: b, primary: brand).copyWith(
    surface: dark ? const Color(0xFF2B2D31) : Colors.white,
  );
  final card = dark ? const Color(0xFF36393F) : Colors.white;
  final line = (dark ? Colors.white : Colors.black).withValues(alpha: dark ? .14 : .12);
  return ThemeData(
    colorScheme: scheme,
    useMaterial3: true,
    scaffoldBackgroundColor: dark ? const Color(0xFF2B2D31) : const Color(0xFFFAF8F7),
    appBarTheme: AppBarTheme(backgroundColor: Colors.transparent, scrolledUnderElevation: 0, centerTitle: false, foregroundColor: scheme.onSurface),
    cardTheme: CardThemeData(
      color: card,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20), side: BorderSide(color: line.withValues(alpha: .08))),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(88, 52),
        shape: const StadiumBorder(),
        textStyle: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(48), shape: const StadiumBorder()),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: card,
      border: _border(line),
      enabledBorder: _border(line),
      focusedBorder: _border(brand, 1.5),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: card,
      indicatorColor: dark ? const Color(0xFF5C3B2C) : const Color(0xFFFFE4D6),
    ),
    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: card,
      showDragHandle: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(28))),
    ),
  );
}
