import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:hotel_app/api.dart';
import 'package:hotel_app/i18n.dart';
import 'package:hotel_app/rider/logic.dart';
import 'package:hotel_app/rider/session.dart';
import 'package:hotel_app/util.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

Applicant good() => Applicant()
  ..name = 'Wafula Simiyu Barasa'
  ..nationalId = '30123456'
  ..phone = '0733 111 222'
  ..residence = 'Kanduyi, near the stage'
  ..bikePlate = 'kmfb 123c'
  ..bikeDescription = 'Red Boxer 150 with a black box'
  ..kin = 'Nafula Barasa'
  ..kinPhone = '0733999888'
  ..password = 'rider-pass-123';

void main() {
  group('bike number plate', () {
    test('is tidied to capital letters and digits', () {
      expect(tidyPlate(' kmfb-123c '), 'KMFB123C');
      expect(tidyPlate('KBZ 123A'), 'KBZ123A');
    });

    test('needs 5-10 characters with both letters and digits', () {
      expect(validPlate('KMFB 123C'), isTrue);
      expect(validPlate('12'), isFalse);
      expect(validPlate('KMFB'), isFalse); // no digits
      expect(validPlate('12345'), isFalse); // no letters
      expect(validPlate('KMFB1234567'), isFalse); // too long
    });
  });

  group('sign-up checks (the same rules as the server)', () {
    test('a complete application passes', () => expect(checkApplicant(good()), isEmpty));

    test('each bad field is named', () {
      expect(checkApplicant(good()..name = 'Wafula').keys, ['name']);
      expect(checkApplicant(good()..nationalId = '12AB').keys, ['national_id']);
      expect(checkApplicant(good()..phone = '12345').keys, ['phone']);
      expect(checkApplicant(good()..residence = 'ab').keys, ['residence_area']);
      expect(checkApplicant(good()..bikePlate = 'KMFB').keys, ['bike_plate']);
      expect(checkApplicant(good()..bikeDescription = 'ab').keys, ['bike_description']);
      expect(checkApplicant(good()..kin = 'Nafula').keys, ['next_of_kin']);
      expect(checkApplicant(good()..kinPhone = '999').keys, ['next_of_kin_phone']);
      expect(checkApplicant(good()..password = 'short').keys, ['password']);
    });

    test("next of kin can't have the rider's own number, however it is typed", () {
      expect(checkApplicant(good()..kinPhone = '+254 733 111 222').keys, ['next_of_kin_phone']);
    });

    test('the password is not checked when fixing an existing application', () {
      expect(checkApplicant(good()..password = '', needPassword: false), isEmpty);
    });

    test('server field names map to the right sign-up step', () {
      expect(stepOfField('bike_plate'), 1);
      expect(stepOfField('selfie'), 2);
      expect(stepOfField('logbook'), 2);
      expect(stepOfField('consent'), 3);
    });
  });

  group('phone numbers', () {
    test('Kenyan formats become 254...', () {
      expect(kenyanNumber('0712 345 678'), '254712345678');
      expect(kenyanNumber('+254712345678'), '254712345678');
      expect(kenyanNumber('254712345678'), '254712345678');
      expect(kenyanNumber('712345678'), '254712345678');
      expect(kenyanNumber('0112345678'), '254112345678');
    });

    test('anything else is not a number we can call', () {
      expect(kenyanNumber(null), isNull);
      expect(kenyanNumber(''), isNull);
      expect(kenyanNumber('12345'), isNull);
      expect(kenyanNumber('0212345678'), isNull);
    });
  });

  group('login cookie', () {
    test('is read from the Set-Cookie header', () {
      expect(refreshFromSetCookie('chakula_refresh=abc123; Path=/api; HttpOnly; Max-Age=100'), 'abc123');
      expect(refreshFromSetCookie('other=1, chakula_refresh=zzz; Path=/'), 'zzz');
      expect(refreshFromSetCookie(null), isNull);
      expect(refreshFromSetCookie('other=1'), isNull);
    });
  });

  group('job stages', () {
    Json job(String status, {bool mine = true}) => {'status': status, 'mine': mine};

    test("someone else's or unclaimed job is open", () => expect(jobStage(job('ready', mine: false)), JobStage.open));

    test('my job moves hotel -> food ready -> on the road -> at the door', () {
      expect(jobStage(job('accepted')), JobStage.toHotel);
      expect(jobStage(job('preparing')), JobStage.toHotel);
      expect(jobStage(job('ready')), JobStage.readyAtHotel);
      expect(jobStage(job('picked_up')), JobStage.toCustomer);
      expect(jobStage(job('on_the_way')), JobStage.atDoor);
    });

    test('the progress bar only moves forward', () {
      final steps = [JobStage.open, JobStage.toHotel, JobStage.readyAtHotel, JobStage.toCustomer, JobStage.atDoor].map(jobStep).toList();
      expect(steps, [0, 1, 2, 3, 3]);
    });

    test('location sharing speeds up only while a delivery is on the road', () {
      expect(onTheRoad([job('preparing')]), isFalse);
      expect(onTheRoad([job('picked_up')]), isTrue);
      expect(onTheRoad([job('on_the_way', mine: false)]), isFalse);
    });
  });

  group('earnings', () {
    test('adds only deliveries finished today', () {
      final now = DateTime(2026, 10, 8, 15, 0);
      final today = DateTime(2026, 10, 8, 9, 30).toUtc().toIso8601String();
      final yesterday = DateTime(2026, 10, 7, 21, 0).toUtc().toIso8601String();
      final rows = <Json>[
        {'status': 'delivered', 'closed_at': today, 'rider_fee': 100},
        {'status': 'delivered', 'closed_at': today, 'rider_fee': 150},
        {'status': 'delivered', 'closed_at': yesterday, 'rider_fee': 200},
        {'status': 'failed_delivery', 'closed_at': today, 'rider_fee': 100},
        {'status': 'delivered', 'closed_at': null, 'rider_fee': 100},
      ];
      expect(earnedToday(rows, now), 250);
    });
  });

  test('directions open the driving route to the stop', () {
    final u = directionsTo(0.5635, 34.5606);
    expect(u.host, 'www.google.com');
    expect(u.queryParameters['destination'], '0.5635,34.5606');
  });

  group('Kiswahili for the new screens', () {
    tearDown(() => lang.value = 'en');
    test('rider and PIN phrases are translated', () {
      lang.value = 'sw';
      expect(tr('Pickup PIN'), 'PIN ya kuchukua');
      expect(tr('Take this job'), 'Chukua kazi hii');
      expect(tr('Hi {name}', {'name': 'Wafula'}), 'Hujambo Wafula');
    });
  });

  group('RiderSession (against a pretend server)', () {
    const cookie = {'set-cookie': 'chakula_refresh=refresh-1; Path=/api/v1/auth; HttpOnly'};
    Map<String, dynamic> token(String role, {bool mustChange = false}) => {
          'access_token': 'access-1',
          'token_type': 'bearer',
          'user': {'id': 'u1', 'role': role, 'hotel_id': null, 'name': 'Wafula', 'phone': '254733111222', 'must_change_password': mustChange},
        };
    final me = {'name': 'Wafula Simiyu Barasa', 'kyc_status': 'approved', 'is_online': false, 'bike_plate': 'KMFB123C'};

    setUp(() => SharedPreferences.setMockInitialValues({}));

    http.Response json(Object body, [int status = 200, Map<String, String> headers = const {}]) =>
        http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json', ...headers});

    test('signing in keeps the login, loads the profile and remembers the refresh token', () async {
      await http.runWithClient(() async {
        final s = RiderSession();
        await s.signIn('0733111222', 'rider-pass-123');
        expect(s.signedIn, isTrue);
        expect(s.status, 'approved');
        expect(s.me?['bike_plate'], 'KMFB123C');
        expect((await SharedPreferences.getInstance()).getString('rider_refresh'), 'refresh-1');
      }, () => MockClient((req) async {
        if (req.url.path.endsWith('/auth/login')) return json(token('rider'), 200, cookie);
        if (req.url.path.endsWith('/rider/me')) {
          expect(req.headers['Authorization'], 'Bearer access-1'); // the login is attached
          return json(me);
        }
        return json({'error': {'code': 'not_found', 'message': 'x'}}, 404);
      }));
    });

    test('a customer or hotel login is refused and nothing is kept', () async {
      await http.runWithClient(() async {
        final s = RiderSession();
        await expectLater(s.signIn('0711000000', 'whatever1'), throwsA(isA<ApiError>().having((e) => e.code, 'code', 'not_rider')));
        expect(s.signedIn, isFalse);
        expect((await SharedPreferences.getInstance()).getString('rider_refresh'), isNull);
      }, () => MockClient((req) async => json(token('customer'), 200, cookie)));
    });

    test('a wrong password shows as a 401', () async {
      await http.runWithClient(() async {
        await expectLater(RiderSession().signIn('0733111222', 'nope'), throwsA(isA<ApiError>().having((e) => e.status, 'status', 401)));
      }, () => MockClient((req) async => json({'error': {'code': 'invalid_credentials', 'message': 'Wrong phone number or password'}}, 401)));
    });

    test('an expired access token is renewed quietly and the call is retried', () async {
      var jobsCalls = 0;
      await http.runWithClient(() async {
        final s = RiderSession();
        await s.signIn('0733111222', 'rider-pass-123');
        final jobs = await s.call('GET', '/rider/jobs') as List;
        expect(jobs, isEmpty);
        expect(jobsCalls, 2); // refused once, then retried with the new token
      }, () => MockClient((req) async {
        final p = req.url.path;
        if (p.endsWith('/auth/login')) return json(token('rider'), 200, cookie);
        if (p.endsWith('/rider/me')) return json(me);
        if (p.endsWith('/auth/refresh')) {
          expect(jsonDecode(req.body)['refresh_token'], 'refresh-1');
          return json({...token('rider'), 'access_token': 'access-2'}, 200, {'set-cookie': 'chakula_refresh=refresh-2; Path=/'});
        }
        if (p.endsWith('/rider/jobs')) {
          jobsCalls++;
          return req.headers['Authorization'] == 'Bearer access-2' ? json([]) : json({'error': {'code': 'unauthorized', 'message': 'expired'}}, 401);
        }
        return json({}, 404);
      }));
    });

    test('a refresh token the server rejects signs the rider out', () async {
      SharedPreferences.setMockInitialValues({'rider_refresh': 'old'});
      await http.runWithClient(() async {
        final s = RiderSession();
        await s.init();
        expect(s.signedIn, isFalse);
        expect((await SharedPreferences.getInstance()).getString('rider_refresh'), isNull);
      }, () => MockClient((req) async => json({'error': {'code': 'invalid_refresh', 'message': 'Please log in again'}}, 401)));
    });

    test('opening the app again restores the login from the saved refresh token', () async {
      SharedPreferences.setMockInitialValues({'rider_refresh': 'saved'});
      await http.runWithClient(() async {
        final s = RiderSession();
        await s.init();
        expect(s.signedIn, isTrue);
        expect(s.me?['name'], 'Wafula Simiyu Barasa');
      }, () => MockClient((req) async {
        if (req.url.path.endsWith('/auth/refresh')) return json(token('rider'), 200, {'set-cookie': 'chakula_refresh=saved-2; Path=/'});
        return json(me);
      }));
    });

    test('signing up sends the form with the bike details and photos, then signs in', () async {
      late http.BaseRequest sent;
      String body = '';
      await http.runWithClient(() async {
        final s = RiderSession();
        await s.apply(
          {'name': 'Wafula Simiyu Barasa', 'bike_plate': 'KMFB123C', 'bike_description': 'Red Boxer', 'consent': 'true'},
          {'id_front': [1, 2, 3], 'id_back': [1, 2, 3], 'selfie': [1, 2, 3], 'logbook': [4, 5]},
        );
        expect(s.signedIn, isTrue);
        expect(sent.url.path, endsWith('/riders/apply'));
        expect(body, contains('bike_plate'));
        expect(body, contains('KMFB123C'));
        for (final f in ['id_front', 'id_back', 'selfie', 'logbook']) {
          expect(body, contains('name="$f"'));
        }
      }, () => MockClient((req) async {
        if (req.url.path.endsWith('/riders/apply')) {
          sent = req;
          body = utf8.decode(req.bodyBytes, allowMalformed: true);
          return json(token('rider'), 201, cookie);
        }
        return json({...me, 'kyc_status': 'pending'});
      }));
    });

    test('a field error from the server keeps its field name', () async {
      await http.runWithClient(() async {
        await expectLater(
          RiderSession().apply({}, {}),
          throwsA(isA<ApiError>().having((e) => e.extra['field'], 'field', 'logbook').having((e) => e.code, 'code', 'bad_photo')),
        );
      }, () => MockClient((req) async => json({'error': {'code': 'bad_photo', 'message': "The logbook photo couldn't be read.", 'field': 'logbook'}}, 422)));
    });

    test('signing out clears everything', () async {
      await http.runWithClient(() async {
        final s = RiderSession();
        await s.signIn('0733111222', 'rider-pass-123');
        await s.signOut();
        expect(s.signedIn, isFalse);
        expect(s.me, isNull);
        expect((await SharedPreferences.getInstance()).getString('rider_refresh'), isNull);
      }, () => MockClient((req) async {
        if (req.url.path.endsWith('/auth/login')) return json(token('rider'), 200, cookie);
        if (req.url.path.endsWith('/rider/me')) return json(me);
        return http.Response('', 204);
      }));
    });
  });
}
