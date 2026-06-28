import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'main_screen.dart';
import 'screens/login_screen.dart';
import 'services/auth_service.dart';
import 'services/network_spider.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await AuthService.init();
  await NetworkSpider.init();
  final hasAccount = await AuthService.hasAccount();
  
  runApp(FeedoSocialApp(hasAccount: hasAccount));
}

class FeedoSocialApp extends StatelessWidget {
  final bool hasAccount;
  const FeedoSocialApp({super.key, required this.hasAccount});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Feedo',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.light,
        scaffoldBackgroundColor: Colors.white,
        primaryColor: Colors.black87,
        colorScheme: const ColorScheme.light(
          primary: Colors.black87,
          secondary: Colors.blueAccent,
          surface: Colors.white,
        ),
        textTheme: GoogleFonts.interTextTheme(
          ThemeData.light().textTheme,
        ),
        appBarTheme: const AppBarTheme(
          backgroundColor: Colors.white,
          foregroundColor: Colors.black87,
          elevation: 0,
        ),
        useMaterial3: true,
      ),
      home: hasAccount ? const MainScreen() : const LoginScreen(),
    );
  }
}

