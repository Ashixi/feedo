import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class AppTheme {
  static ThemeData get darkTheme {
    return ThemeData.dark().copyWith(
      scaffoldBackgroundColor: const Color(0xFF0f0d0b),
      primaryColor: const Color(0xFFC05640), 
      colorScheme: const ColorScheme.dark(
        primary: Color(0xFFC05640), // Terracotta
        secondary: Color(0xFFC05640), // Terracotta as secondary
        surface: Color(0xFF1a1613),
      ),
      textTheme: GoogleFonts.outfitTextTheme(ThemeData.dark().textTheme),
      cardTheme: CardThemeData(
        color: const Color(0xFF1a1613),
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(color: Color(0x33FFFFFF), width: 1),
        ),
      ),
      dividerTheme: const DividerThemeData(
        color: Color(0x26FFFFFF),
        thickness: 1,
      ),
    );
  }
}
