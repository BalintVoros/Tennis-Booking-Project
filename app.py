# -*- coding: utf-8 -*-
import os
import pyodbc

from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
# =================
from werkzeug.security import generate_password_hash, check_password_hash
import datetime


app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'c3f5a1e8b9d7a4c2e1f8b7a6d5e4f3a2')
@app.context_processor
def inject_now():
    """Globálisan elérhetővé teszi a datetime.datetime.utcnow-t a sablonokban 'now' néven."""

    return {'now': datetime.datetime.utcnow}
# --- Adatbázis Konfiguráció ---

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Ellenőrizzük, hogy a felhasználó be van-e jelentkezve és admin-e
        if 'user_id' not in session or session.get('user_role') != 'admin':
            flash('Nincs jogosultságod ehhez a művelethez.', 'danger')
            # Átirányítás loginra vagy főoldalra attól függően, be van-e jelentkezve
            if 'user_id' not in session:
                return redirect(url_for('login', next=request.url))
            else:
                return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function
# =========================
DB_CONFIG = {
    'driver': '{ODBC Driver 17 for SQL Server}', 
    'server': 'BALINTPC',                     
    'database': 'TennisBookingDB',            
    'trusted_connection': 'yes',             
    'uid': '',                               
    'pwd': ''                                
}


def get_db_conn():
    """Létrehoz és visszaad egy adatbázis kapcsolatot a DB_CONFIG alapján."""
    conn = None
    try:
        conn_str_parts = [
            f"DRIVER={DB_CONFIG['driver']}",
            f"SERVER={DB_CONFIG['server']}",
            f"DATABASE={DB_CONFIG['database']}",
        ]
        if DB_CONFIG['trusted_connection'].lower() == 'yes':
            conn_str_parts.append("Trusted_Connection=yes")
        else:
            conn_str_parts.append(f"UID={DB_CONFIG['uid']}")
            conn_str_parts.append(f"PWD={DB_CONFIG['pwd']}")

        conn_str = ';'.join(conn_str_parts)
       
        conn = pyodbc.connect(conn_str, autocommit=False)
        return conn
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        print(f"!!! Adatbázis kapcsolódási hiba ({sqlstate}): {ex}")
        flash(f"Adatbázis kapcsolódási hiba: {ex}", "danger")
        return None
    except Exception as e:
        print(f"!!! Általános hiba a kapcsolat létrehozásakor: {e}")
        flash("Általános hiba a kapcsolat létrehozásakor.", "danger")
        return None


@app.route('/api/courts')
def api_courts():
    """Visszaadja a pályák listáját JSON formátumban a FullCalendar 'resources' számára."""
    if 'user_id' not in session: 
        return jsonify({"error": "Authentication required"}), 401

    courts_list = []
    conn = get_db_conn()
    if conn:
        cursor = None
        try:
            cursor = conn.cursor()
        
            cursor.execute("SELECT CourtID, CourtNumber FROM Courts ORDER BY CourtNumber")
            courts_raw = cursor.fetchall()
          
            courts_list = [{"id": str(row.CourtID), "title": f"Pálya {row.CourtNumber}"} for row in courts_raw]
        except pyodbc.Error as ex:
            print(f"Hiba az API /api/courts lekérdezéskor: {ex}")
            return jsonify({"error": "Database query failed"}), 500
        finally:
            if cursor: cursor.close()
            conn.close()
    else:
        return jsonify({"error": "Database connection failed"}), 500

    return jsonify(courts_list)
@app.route('/api/bookings')
def api_bookings():
    """Visszaadja a foglalásokat JSON 'event' formátumban a FullCalendar számára.
       Elfogad 'start' és 'end' query paramétereket a dátum szűréshez."""
    if 'user_id' not in session: 
       return jsonify({"error": "Authentication required"}), 401


    start_str = request.args.get('start') # Formátum: YYYY-MM-DDTHH:MM:SSZ vagy YYYY-MM-DD
    end_str = request.args.get('end')


    bookings_list = []
    conn = get_db_conn()
    if conn:
        cursor = None
        try:
            cursor = conn.cursor()
         
            sql = """
                SELECT b.BookingID, b.StartTime, b.EndTime, b.CourtID, u.Name as UserName
                FROM CourtBookings b
                JOIN Users u ON b.UserID = u.UserID
                WHERE b.BookingStatus = 'Confirmed'
                  AND b.EndTime >= GETDATE() -- EGYSZERŰSÍTETT SZŰRÉS! Élesben start/end paraméterek kellenek!
                  -- AND b.StartTime < @EndDate -- Példa szűrésre
                  -- AND b.EndTime > @StartDate -- Példa szűrésre
                ORDER BY b.StartTime;
            """
       
            cursor.execute(sql) 
            bookings_raw = cursor.fetchall()

       
            for row in bookings_raw:
                bookings_list.append({
                    "id": row.BookingID,
                    "title": f"Foglalt ({row.UserName})",
                    "start": row.StartTime.isoformat(), 
                    "end": row.EndTime.isoformat(),     
                    "resourceId": str(row.CourtID)      
                
                })

        except pyodbc.Error as ex:
            print(f"Hiba az API /api/bookings lekérdezéskor: {ex}")
            return jsonify({"error": "Database query failed"}), 500
        finally:
            if cursor: cursor.close()
            conn.close()
    else:
        return jsonify({"error": "Database connection failed"}), 500

    return jsonify(bookings_list)



@app.route('/calendar')
def calendar_view():
    """Megjeleníti a naptár oldalt."""
    if 'user_id' not in session:
        flash("A naptár megtekintéséhez be kell jelentkezni!", "warning")
        return redirect(url_for('login'))

    return render_template('calendar.html')
@app.route('/')
def home():
    """A főoldal route-ja, kilistázza a pályákat."""
    courts = []
    conn = get_db_conn()
    if conn:
        cursor = None
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT CourtID, CourtNumber, SurfaceType, LocationType, PricePerHour FROM Courts ORDER BY CourtNumber")
            columns = [column[0] for column in cursor.description]
            courts = [dict(zip(columns, row)) for row in cursor.fetchall()]
        except pyodbc.Error as ex:
            print(f"Hiba a pályák lekérdezésekor: {ex}")
            flash(f"Hiba történt a pályák betöltése közben: {ex}", "danger")
        finally:
            if cursor: cursor.close()
            conn.close()
    return render_template('home.html', courts=courts)

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Felhasználói regisztráció kezelése."""
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        error = None

        if not name: error = 'A név megadása kötelező.'
        elif not email: error = 'Az email cím megadása kötelező.'
        elif not password: error = 'A jelszó megadása kötelező.'

        if error is None:
            hashed_password = generate_password_hash(password)
            conn = get_db_conn()
            if conn:
                cursor = None
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT UserID FROM Users WHERE Email = ?", (email,))
                    existing_user = cursor.fetchone()

                    if existing_user:
                        error = f"Az email cím ({email}) már regisztrálva van."
                    else:
                        cursor.execute("INSERT INTO Users (Name, Email, PasswordHash, MemberStatus) VALUES (?, ?, ?, ?)",
                                       (name, email, hashed_password, 'Active'))
                        conn.commit() # Változtatások véglegesítése
                        flash('Sikeres regisztráció! Most már bejelentkezhetsz.', 'success')
                        return redirect(url_for('login'))
                except pyodbc.Error as ex:
                    conn.rollback()
                    print(f"Regisztrációs adatbázis hiba: {ex}")
                    error = "Hiba történt a regisztráció során. Próbáld újra később."
                finally:
                    if cursor: cursor.close()
                    conn.close()
            else:
                error = "Adatbázis kapcsolati hiba a regisztráció során."

        if error: flash(error, 'danger')

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Felhasználói bejelentkezés kezelése."""
    if 'user_id' in session:
        return redirect(url_for('home'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        error = None

        if not email: error = 'Email cím megadása kötelező.'
        elif not password: error = 'Jelszó megadása kötelező.'

        if error is None:
            conn = get_db_conn()
            if conn:
                cursor = None
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT UserID, Name, Email, PasswordHash, MemberStatus, Role FROM Users WHERE Email = ?", (email,))
                    user_row = cursor.fetchone()

                    if user_row:
                        print(f"DEBUG (login): Felhasználó talált: ID={user_row[0]}, Email={user_row[2]}, Role={user_row[5]}, Status={user_row[4]}") 
                    else:
                        print(f"DEBUG (login): Felhasználó NEM talált: Email={email}")

                    if user_row is None or not check_password_hash(user_row[3], password):
                        error = 'Hibás email cím vagy jelszó.'
                    elif user_row[4] != 'Active': 
                         error = f'Ez a felhasználói fiók jelenleg nem aktív ({user_row[4]}).'
                    else:
                        # Sikeres bejelentkezés
                        session.clear()
                        session['user_id'] = user_row[0] 
                        session['user_name'] = user_row[1] 
                        session['user_role'] = user_row[5] 

                        print(f"DEBUG (login): Szerepkör beállítva a session-ben: {session.get('user_role')}")
                        # =================================================

                        flash(f'Sikeres bejelentkezés, üdv {session.get("user_name")}!', 'success') 
                        if session.get('user_role') == 'admin':
                             return redirect(url_for('admin_dashboard'))
                        else:
                            return redirect(url_for('home'))

                except pyodbc.Error as ex:
                    print(f"Bejelentkezési adatbázis hiba: {ex}")
                    error = "Hiba történt a bejelentkezés során."
                except IndexError: 
                    print(f"DEBUG (login): Index hiba - Valószínűleg a 'Role' oszlop hiányzik a lekérdezés eredményéből.")
                    error = "Belső hiba történt a bejelentkezés során (adatstruktúra)."
                finally:
                    if cursor: cursor.close()
                    conn.close()
            else:
                error = "Adatbázis kapcsolati hiba a bejelentkezés során."

            if error: flash(error, 'danger')

    return render_template('login.html')


@app.route('/logout')
def logout():
    """Felhasználó kijelentkeztetése."""
    session.pop('user_id', None)
    session.pop('user_name', None)
    flash('Sikeresen kijelentkeztél.', 'info')
    return redirect(url_for('login'))


@app.route('/new_booking')
def new_booking_form():
    """Lekérdezi a pályákat/ESZKÖZÖKET és megjeleníti a foglalási űrlapot."""
    if 'user_id' not in session:
        flash("A foglaláshoz be kell jelentkezni!", "warning")
        return redirect(url_for('login'))

    print("Új foglalási űrlap kérése...")
    conn = get_db_conn()
    cursor = None
    courts = []
    equipment_list = []
    error_message = None

    if conn:
        try:
            cursor = conn.cursor()
            print("Pályák lekérdezése az űrlaphoz...")
            cursor.execute("SELECT CourtID, CourtNumber, SurfaceType, LocationType, PricePerHour FROM Courts ORDER BY CourtNumber")
            court_columns = [column[0] for column in cursor.description]
            courts = [dict(zip(court_columns, row)) for row in cursor.fetchall()]
            print(f"Pályák lekérdezve: {len(courts)} db")

            print("Eszközök lekérdezése az űrlaphoz...")
            cursor.execute("""
                SELECT EquipmentID, EquipmentType, Brand, Model, QuantityInStock, RentalPrice
                FROM Equipment WHERE QuantityInStock > 0 ORDER BY EquipmentType, Brand, Model
            """)
            equip_columns = [column[0] for column in cursor.description]
            equipment_list = [dict(zip(equip_columns, row)) for row in cursor.fetchall()]
            print(f"Eszközök lekérdezve: {len(equipment_list)} db")

        except pyodbc.Error as ex:
            error_message = "Hiba történt az űrlap adatainak betöltésekor."
            print(f"Hiba a pályák/eszközök lekérdezésekor az űrlaphoz: {ex}")
            flash(error_message, "danger")
        finally:
            if cursor: cursor.close()
            conn.close()
            print("Adatbázis kapcsolat lezárva (new_booking_form).")
    else:
         error_message = "Nem sikerült csatlakozni az adatbázishoz az űrlap betöltésekor!"

    return render_template('booking_form.html', courts=courts, equipment_list=equipment_list, error=error_message)


@app.route('/book', methods=['POST'])
def add_booking():
    """Fogadja az űrlap adatait, meghívja az sp_CreateBooking és sp_AddRentalToBooking eljárásokat."""
    if 'user_id' not in session:
        flash("A foglalás rögzítéséhez be kell jelentkezni!", "warning")
        return redirect(url_for('login'))

    user_id = session['user_id']

    court_id_str = request.form.get('court_id')
    start_time_str = request.form.get('start_time')
    end_time_str = request.form.get('end_time')
    selected_equipment_ids = request.form.getlist('selected_equipment')

    print(f"Foglalási kísérlet: UserID={user_id}, CourtID={court_id_str}, Start={start_time_str}, End={end_time_str}, Eszközök={selected_equipment_ids}")

    error = None
    court_id = None
    start_time_dt = None
    end_time_dt = None

    if not court_id_str: error = "Pálya kiválasztása kötelező."
    elif not start_time_str: error = "Kezdő időpont megadása kötelező."
    elif not end_time_str: error = "Befejező időpont megadása kötelező."
    else:
        try:
            court_id = int(court_id_str)
            start_time_dt = datetime.datetime.fromisoformat(start_time_str)
            end_time_dt = datetime.datetime.fromisoformat(end_time_str)
            if start_time_dt >= end_time_dt: error = "A foglalás vége nem lehet korábbi vagy azonos a kezdetével!"
        except ValueError:
            error = "Érvénytelen szám vagy dátum formátum."

    if error:
        flash(error, "danger")
        return redirect(url_for('new_booking_form'))

    # --- Adatbázis Műveletek ---
    conn = get_db_conn()
    cursor = None
    new_booking_id = None
    final_flash_message = ""
    flash_category = "danger" 

    if not conn:
         return redirect(url_for('new_booking_form'))

    try:
        cursor = conn.cursor()

        # 1. PÁLYAFOGLALÁS (sp_CreateBooking hívása)
        print(f"Hívás: sp_CreateBooking({user_id}, {court_id}, '{start_time_dt}', '{end_time_dt}')")
        sql_book = """
            DECLARE @NewBookingID_Out INT = NULL;
            DECLARE @StatusMessage_Out NVARCHAR(255) = N'';
            EXEC sp_CreateBooking ?, ?, ?, ?, @NewBookingID = @NewBookingID_Out OUTPUT, @StatusMessage = @StatusMessage_Out OUTPUT;
            SELECT @NewBookingID_Out AS FinalBookingID, @StatusMessage_Out AS FinalStatusMessage;
        """
        params_book = (user_id, court_id, start_time_dt, end_time_dt)
        cursor.execute(sql_book, params_book)
        result_book = cursor.fetchone()

        if result_book:
            new_booking_id = result_book[0]
            court_status_message = result_book[1]
            print(f"sp_CreateBooking eredmény: ID={new_booking_id}, Msg='{court_status_message}'")
        else:
            court_status_message = "Hiba: A pályafoglalási eljárás nem adott vissza eredményt."
            print(court_status_message)
            raise Exception(court_status_message)

        if new_booking_id is None or "HIBA" in court_status_message:
            final_flash_message = court_status_message
            raise Exception("Pályafoglalás sikertelen.")

        final_flash_message += court_status_message

        # 2. ESZKÖZKÖLCSÖNZÉS
        rental_errors = []
        rental_success_count = 0
        if selected_equipment_ids:
            print(f"Eszközök hozzáadása ({len(selected_equipment_ids)} db)...")
            sql_rent = """
                DECLARE @RentalStatusMessage_Out NVARCHAR(255) = N'';
                EXEC sp_AddRentalToBooking ?, ?, ?, ?, @StatusMessage = @RentalStatusMessage_Out OUTPUT;
                SELECT @RentalStatusMessage_Out AS RentalStatusMessage;
            """
            for equip_id_str in selected_equipment_ids:
                try:
                    equip_id = int(equip_id_str)
                    quantity = 1 
                    print(f"Hívás: sp_AddRentalToBooking({new_booking_id}, {user_id}, {equip_id}, {quantity})")
                    params_rent = (new_booking_id, user_id, equip_id, quantity)
                    # =========================================
                    cursor.execute(sql_rent, params_rent)
                    result_rent = cursor.fetchone()
                    rental_status = result_rent[0] if result_rent else "!! NEM JÖTT VISSZA KÖLCSÖNZÉSI STÁTUSZ !!"
                    print(f"DEBUG: Visszatért státusz (Eszköz ID: {equip_id}): '{rental_status}'")

                    if "HIBA" in rental_status:
                        rental_errors.append(f"Eszköz ID {equip_id}: {rental_status}")
                    else:
                        rental_success_count += 1
                except ValueError:
                    rental_errors.append(f"Érvénytelen eszköz ID formátum: {equip_id_str}")

        if not rental_errors:
            conn.commit()
            print("Python oldali COMMIT sikeres.")
            if rental_success_count > 0: final_flash_message += f" || Sikeresen hozzáadva {rental_success_count} eszköz."
            flash_category = "success"
        else:
            conn.rollback()
            print("Python oldali ROLLBACK kölcsönzési hiba miatt.")
            final_flash_message += " || Hibák a kölcsönzés során: " + " | ".join(rental_errors) + ". A teljes foglalás (pálya is) visszavonva."
            flash_category = "warning"

    except Exception as ex:
        print(f"Hiba az /book route feldolgozása során: {ex}")
        if not final_flash_message or "HIBA" not in final_flash_message:
             final_flash_message = f"Váratlan hiba történt a foglalás feldolgozása során."
        flash_category = "danger"
        try:
            if conn:
                 print("Kísérlet Python oldali ROLLBACK-re kivétel miatt...")
                 conn.rollback()
                 print("Python oldali ROLLBACK kivétel miatt sikeresnek tűnik.")
        except Exception as rb_ex:
             print(f"Hiba a Python oldali rollback során kivétel után: {rb_ex}")

    finally:
        if cursor: cursor.close()
        if conn: conn.close()
        print("Adatbázis kapcsolat lezárva (/book).")

    flash(final_flash_message, flash_category)
    return redirect(url_for('home'))


@app.route('/my_bookings')
def my_bookings():
    """Lekérdezi és megjeleníti a bejelentkezett felhasználó foglalásait."""
    if 'user_id' not in session:
        flash("A foglalásaid megtekintéséhez be kell jelentkezni!", "warning")
        return redirect(url_for('login'))

    user_id = session['user_id']
    bookings = []
    conn = get_db_conn()
    if conn:
        cursor = None
        try:
            cursor = conn.cursor()
            sql = """
                SELECT b.BookingID, b.StartTime, b.EndTime, b.BookingStatus,
                       c.CourtNumber, c.SurfaceType, c.LocationType
                FROM CourtBookings b
                JOIN Courts c ON b.CourtID = c.CourtID
                WHERE b.UserID = ?
                  AND b.BookingStatus = 'Confirmed'
                  AND b.EndTime >= GETDATE()
                ORDER BY b.StartTime;
            """
            cursor.execute(sql, user_id)
            columns = [column[0] for column in cursor.description]
            bookings = [dict(zip(columns, row)) for row in cursor.fetchall()]
        except pyodbc.Error as ex:
            print(f"Hiba a saját foglalások lekérdezésekor: {ex}")
            flash("Hiba történt a foglalások betöltésekor.", "danger")
        finally:
            if cursor: cursor.close()
            conn.close()

    return render_template('my_bookings.html', bookings=bookings)

@app.route('/booking/<int:booking_id>')
def booking_details(booking_id):
     if 'user_id' not in session:
        flash("A foglalás részleteinek megtekintéséhez be kell jelentkezni!", "warning")
        return redirect(url_for('login'))

     user_id_from_session = session['user_id']
     user_role = session.get('user_role') 

     booking = None
     rentals = []
     court_price = 0.0
     total_rental_price = 0.0
     total_price = 0.0

     conn = get_db_conn()
     if not conn:
         return redirect(url_for('my_bookings'))

     cursor = None
     try:
        cursor = conn.cursor()

        sql_booking = """
            SELECT b.BookingID, b.StartTime, b.EndTime, b.BookingStatus, b.UserID,
                   u.Name AS UserName, u.Email AS UserEmail,
                   c.CourtNumber, c.SurfaceType, c.LocationType, c.PricePerHour
            FROM CourtBookings b
            JOIN Users u ON b.UserID = u.UserID
            JOIN Courts c ON b.CourtID = c.CourtID
            WHERE b.BookingID = ?;
        """

        cursor.execute(sql_booking, booking_id) 
        booking_raw = cursor.fetchone()

        if not booking_raw:
            flash(f"Hiba: Nem található foglalás ezzel az ID-val: {booking_id}", "danger")
            return redirect(url_for('my_bookings'))

        try:
             columns = [column[0] for column in cursor.description]
             booking = dict(zip(columns, booking_raw))
        except Exception as e:
             print(f"Hiba a foglalási sor szótárrá alakításakor (details): {e}")
             flash("Belső hiba a foglalási adatok feldolgozásakor.", "danger")
             return redirect(url_for('my_bookings'))

        if booking['UserID'] != user_id_from_session and user_role != 'admin':
             flash("Nincs jogosultságod megtekinteni ezt a foglalást.", "danger")
             return redirect(url_for('my_bookings'))

        # --- Pályaár számítása ---
        if booking.get('PricePerHour') and booking.get('StartTime') and booking.get('EndTime'):
            try:
                duration = booking['EndTime'] - booking['StartTime']
                duration_hours = duration.total_seconds() / 3600.0
                price_per_hour_float = float(booking['PricePerHour'])
                court_price = price_per_hour_float * duration_hours
                print(f"Pályaár kiszámítva: {court_price}")
            except (TypeError, ValueError) as e:
                 print(f"Hiba a pályaár számításakor: {e}. PricePerHour: {booking.get('PricePerHour')}")
                 court_price = 0.0 
        # ---------------------------

        sql_rentals = """
            SELECT r.QuantityRented, e.EquipmentType, e.Brand, e.Model, e.RentalPrice
            FROM EquipmentRentals r JOIN Equipment e ON r.EquipmentID = e.EquipmentID
            WHERE r.BookingID = ? ORDER BY e.EquipmentType;
        """
        cursor.execute(sql_rentals, booking_id)
        rental_columns = [column[0] for column in cursor.description]
        rentals_raw = cursor.fetchall()
        rentals = [dict(zip(rental_columns, row)) for row in rentals_raw]

        # --- Kölcsönzési díj számítása ---
        for rental in rentals:
            try:
                if rental.get('RentalPrice') is not None and rental.get('QuantityRented') is not None:
                     item_price = float(rental['RentalPrice']) * int(rental['QuantityRented'])
                     total_rental_price += item_price
                     rental['calculated_item_price'] = item_price 
                else:
                     rental['calculated_item_price'] = 0.0 
            except (TypeError, ValueError) as e:
                print(f"Hiba egy kölcsönzött tétel árának számításakor: {e}. Adat: {rental}")
                rental['calculated_item_price'] = 0.0 

        print(f"Teljes kölcsönzési díj: {total_rental_price}")
        # --------------------------------

        # --- Teljes ár számítása ---
        total_price = court_price + total_rental_price
        print(f"Teljes fizetendő összeg: {total_price}")
        # --------------------------

     except pyodbc.Error as ex:
        print(f"Hiba a foglalás részleteinek lekérdezésekor (ID: {booking_id}): {ex}")
        flash("Hiba történt a foglalás részleteinek betöltésekor.", "danger")
        booking = None 

     finally:
         if cursor: cursor.close()
         if conn: conn.close()
         print(f"Adatbázis kapcsolat lezárva (booking_details, ID: {booking_id}).")

     return render_template('booking_details.html',
                            booking=booking,
                            rentals=rentals,
                            court_price=court_price,
                            total_rental_price=total_rental_price,
                            total_price=total_price)

@app.route('/cancel/<int:booking_id>', methods=['POST']) # Csak POST kérést fogadunk
def cancel_booking(booking_id):
    if 'user_id' not in session:
        flash("A foglalás lemondásához be kell jelentkezni!", "warning")
        return redirect(url_for('login'))

    user_id_from_session = session['user_id']
    print(f"Lemondási kísérlet: BookingID={booking_id}, UserID={user_id_from_session}")

    conn = get_db_conn()
    if not conn:
        return redirect(url_for('my_bookings')) # Vissza a foglalásaimhoz

    cursor = None
    final_status_message = "Ismeretlen hiba történt a lemondás során."
    flash_category = "danger" # Alapból hiba

    try:
        cursor = conn.cursor()

        # 2. Jogosultság ellenőrzése
        cursor.execute("SELECT UserID, BookingStatus FROM CourtBookings WHERE BookingID = ?", booking_id)
        booking_info = cursor.fetchone()

        if not booking_info:
            final_status_message = f"HIBA: Nem található foglalás ezzel az ID-val: {booking_id}"
        elif booking_info.UserID != user_id_from_session: 
            final_status_message = "HIBA: Nincs jogosultságod lemondani ezt a foglalást."
        elif booking_info.BookingStatus == 'Cancelled':
             final_status_message = "Információ: Ez a foglalás már korábban le lett mondva."
             flash_category = "info" 
        else:
            print(f"Hívás: sp_CancelBooking({booking_id}, {user_id_from_session})")
            sql_cancel = """
                DECLARE @CancelStatusMessage_Out NVARCHAR(255) = N'';
                EXEC sp_CancelBooking ?, ?, @StatusMessage = @CancelStatusMessage_Out OUTPUT;
                SELECT @CancelStatusMessage_Out AS FinalStatusMessage;
            """
            params_cancel = (booking_id, user_id_from_session)
            cursor.execute(sql_cancel, params_cancel)
            result_cancel = cursor.fetchone()

            if result_cancel:
                final_status_message = result_cancel[0] 
                if "HIBA" not in final_status_message:
                    flash_category = "success"
                    conn.commit() 
                    print("Python oldali COMMIT (lemondás) sikeres.")
                else:
                    flash_category = "warning" 
                    conn.rollback() 
                    print("Python oldali ROLLBACK (lemondás) SP hiba miatt.")
            else:
                 final_status_message = "Hiba: A lemondó eljárás nem adott vissza üzenetet."
                 conn.rollback() 
                 print("Python oldali ROLLBACK (lemondás) mert SP nem adott vissza üzenetet.")

    except pyodbc.Error as db_ex:
        print(f"Adatbázis hiba a lemondás során (BookingID: {booking_id}): {db_ex}")
        final_status_message = "Adatbázis hiba történt a lemondás során."
        flash_category = "danger"
        try:
            if conn: conn.rollback() # Próbálkozunk rollbackkel
        except Exception as rb_ex_db: print(f"Rollback hiba (DB Exception): {rb_ex_db}")
    except Exception as e:
        print(f"Általános hiba a lemondás során (BookingID: {booking_id}): {e}")
        final_status_message = f"Általános hiba a lemondás során: {e}"
        flash_category = "danger"
        try:
            if conn: conn.rollback() # Próbálkozunk rollbackkel
        except Exception as rb_ex_gen: print(f"Rollback hiba (General Exception): {rb_ex_gen}")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
        print(f"Adatbázis kapcsolat lezárva (/cancel, BookingID: {booking_id}).")

    flash(final_status_message, flash_category)

    return redirect(url_for('my_bookings'))




@app.route('/profile')
def profile():
    if 'user_id' not in session:
        flash("Ehhez az oldalhoz be kell jelentkezni!", "warning")
        return redirect(url_for('login'))

    user_id = session['user_id']
    user_data = None 

    conn = get_db_conn()
    if conn:
        cursor = None
        try:
            cursor = conn.cursor()
            sql = "SELECT UserID, Name, Email, MemberStatus, Role FROM Users WHERE UserID = ?"
            cursor.execute(sql, user_id)
            user_raw = cursor.fetchone() 

            if user_raw:
                try:
                    columns = [column[0] for column in cursor.description]
                    user_data = dict(zip(columns, user_raw))
                    print(f"DEBUG: Profil oldal adatai betöltve (UserID {user_id}): {user_data}") 
                except Exception as e:
                    print(f"Hiba a profil adatainak szótárrá alakításakor (UserID: {user_id}): {e}")
                    flash("Hiba történt a profiladatok feldolgozása során.", "danger")
            else:
                 flash("Hiba: A felhasználói adatok nem találhatók az adatbázisban.", "danger")
                 session.clear()
                 return redirect(url_for('login'))

        except pyodbc.Error as db_ex:
            print(f"Hiba a profiladatok lekérdezésekor (UserID: {user_id}): {db_ex}")
            flash("Adatbázis hiba történt a profiladatok lekérdezésekor.", "danger")
        except Exception as e:
            print(f"Általános hiba a profiladatok lekérdezésekor/feldolgozásakor (UserID: {user_id}): {e}")
            flash("Váratlan hiba történt a profiladatok lekérdezésekor.", "danger")
        finally:
            if cursor: cursor.close()
            if conn: conn.close()
            print(f"Adatbázis kapcsolat lezárva (profile, UserID: {user_id}).") 
    else:
        pass

    return render_template('profile.html', user_data=user_data)
@app.route('/admin')
@admin_required 
def admin_dashboard():
    return render_template('admin/admin_dashboard.html')

# === FELHASZNÁLÓK LISTÁZÁSA ADMIN SZÁMÁRA ===
@app.route('/admin/users')
@admin_required
def admin_list_users():
    users = []
    conn = get_db_conn()
    if conn:
        cursor = None
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT UserID, Name, Email, MemberStatus, Role FROM Users ORDER BY Role, Name")
            columns = [column[0] for column in cursor.description]
            users = [dict(zip(columns, row)) for row in cursor.fetchall()]
        except pyodbc.Error as ex:
            print(f"Hiba az admin/users lekérdezéskor: {ex}")
            flash("Hiba történt a felhasználók listázása közben.", "danger")
        finally:
            if cursor: cursor.close()
            conn.close()
    return render_template('admin/admin_users.html', users=users)

@app.route('/admin/user/edit/<int:user_id>', methods=['GET'])
@admin_required
def admin_edit_user(user_id):
    """Megjeleníti a felhasználó szerkesztő űrlapot."""
    user = None
    conn = get_db_conn()
    if conn:
        cursor = None
        try:
            cursor = conn.cursor()
            sql = "SELECT UserID, Name, Email, MemberStatus, Role FROM Users WHERE UserID = ?"
            cursor.execute(sql, user_id)
            user_raw = cursor.fetchone() 
            if user_raw:
                try:
                    columns = [column[0] for column in cursor.description]
                    user = dict(zip(columns, user_raw))
                    print(f"DEBUG: Szerkesztendő felhasználó: {user}") # Debug
                except Exception as e:
                    print(f"Hiba a felhasználói sor szótárrá alakításakor: {e}")
                    user = {
                        'UserID': user_raw[0],
                        'Name': user_raw[1],
                        'Email': user_raw[2],
                        'MemberStatus': user_raw[3],
                        'Role': user_raw[4]
                    }

            else:
                flash(f"Hiba: Nem található felhasználó ezzel az ID-val: {user_id}", "danger")
                return redirect(url_for('admin_list_users'))

        except pyodbc.Error as ex:
            print(f"Hiba az admin/user/edit lekérdezéskor (ID: {user_id}): {ex}")
            flash("Hiba történt a felhasználó adatainak betöltésekor.", "danger")
            return redirect(url_for('admin_list_users'))
        finally:
            if cursor: cursor.close()
            if conn: conn.close()
    else:
         return redirect(url_for('admin_list_users'))

    return render_template('admin/admin_edit_user.html', user=user)


@app.route('/admin/user/update', methods=['POST'])
@admin_required
def admin_update_user():
    """Kezeli a felhasználó szerkesztő űrlap elküldését."""
    user_id = request.form.get('user_id')
    name = request.form.get('name')
    email = request.form.get('email')
    member_status = request.form.get('member_status')
    role = request.form.get('role') 

    if not role and user_id == str(session.get('user_id')): # Ha a role üres ÉS saját magunkat szerkesztjük
         role = session.get('user_role', 'user') # Visszaállítjuk a sessionből (vagy 'user' ha nincs)
         print(f"DEBUG: Admin saját szerepköre visszaállítva: {role}")

    # --- Alapvető Validálás ---
    error = None
    allowed_statuses = ['Active', 'Inactive', 'Suspended']
    allowed_roles = ['user', 'admin']

    if not all([user_id, name, email, member_status, role]):
        error = "Minden mező kitöltése kötelező (beleértve a rejtett user_id-t és a szerepkört)."
    elif member_status not in allowed_statuses:
        error = f"Érvénytelen státusz érték: {member_status}. Engedélyezett: {', '.join(allowed_statuses)}"
    elif role not in allowed_roles:
        error = f"Érvénytelen szerepkör érték: {role}. Engedélyezett: {', '.join(allowed_roles)}"
    else:
        try:
            user_id_int = int(user_id)
            # === KRITIKUS ELLENŐRZÉS: Admin ne zárhassa ki magát ===
            if user_id_int == session.get('user_id'):
                if role != 'admin':
                    error = "FIGYELEM: Saját admin szerepkör módosítása 'user'-re nem engedélyezett!"
                    role = 'admin' 
                if member_status != 'Active':
                    error = "FIGYELEM: Saját státusz módosítása 'Active'-ról nem engedélyezett!"
                    member_status = 'Active' 
        except ValueError:
            error = "Érvénytelen felhasználói ID formátum."

    if error:
        flash(f"Hiba a mentés során: {error}", "danger")
        return redirect(url_for('admin_list_users'))

    conn = get_db_conn()
    if not conn:
        return redirect(url_for('admin_list_users'))

    cursor = None
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT Email FROM Users WHERE UserID = ?", user_id_int)
        current_email_row = cursor.fetchone()
        current_email = current_email_row[0] if current_email_row else None

        if current_email is not None and email != current_email:
            cursor.execute("SELECT UserID FROM Users WHERE Email = ? AND UserID != ?", (email, user_id_int))
            existing_user = cursor.fetchone()
            if existing_user:
                 flash(f"Hiba: Az '{email}' email cím már foglalt egy másik felhasználó által.", "danger")
                 conn.rollback()
                 return redirect(url_for('admin_edit_user', user_id=user_id_int)) 

        # === UPDATE végrehajtása ===
        sql_update = """
            UPDATE Users
            SET Name = ?, Email = ?, MemberStatus = ?, Role = ?
            WHERE UserID = ?;
        """
        print(f"DEBUG: Updating UserID {user_id_int} with Name={name}, Email={email}, Status={member_status}, Role={role}")
        cursor.execute(sql_update, name, email, member_status, role, user_id_int)
        conn.commit() 
        flash(f"Felhasználó (ID: {user_id_int}, Név: {name}) adatai sikeresen frissítve.", "success")

    except pyodbc.Error as ex:
        conn.rollback() 
        print(f"Hiba az admin/user/update művelet során (ID: {user_id_int}): {ex}")
        flash("Adatbázis hiba történt a felhasználó frissítésekor.", "danger")
    except Exception as e:
        conn.rollback() 
        print(f"Általános hiba az admin/user/update művelet során (ID: {user_id_int}): {e}")
        flash("Váratlan hiba történt a felhasználó frissítésekor.", "danger")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

    return redirect(url_for('admin_list_users'))


# === Útvonalak az Aktiváláshoz/Deaktiváláshoz ===

@app.route('/admin/user/deactivate/<int:user_id>', methods=['POST'])
@admin_required
def admin_deactivate_user(user_id):
    """Beállítja a felhasználó státuszát 'Inactive'-re."""
    if user_id == session.get('user_id'):
        flash("Hiba: Saját magadat nem deaktiválhatod.", "danger")
        return redirect(url_for('admin_list_users'))

    conn = get_db_conn()
    if not conn: return redirect(url_for('admin_list_users'))
    cursor = None
    try:
        cursor = conn.cursor()
        sql = "UPDATE Users SET MemberStatus = 'Inactive' WHERE UserID = ?"
        cursor.execute(sql, user_id)
        conn.commit()
        flash(f"Felhasználó (ID: {user_id}) sikeresen inaktívvá téve.", "success")
    except pyodbc.Error as ex:
        conn.rollback()
        print(f"Hiba a felhasználó deaktiválásakor (ID: {user_id}): {ex}")
        flash("Adatbázis hiba történt a deaktiválás során.", "danger")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

    return redirect(url_for('admin_list_users'))

@app.route('/admin/user/activate/<int:user_id>', methods=['POST'])
@admin_required
def admin_activate_user(user_id):
    """Beállítja a felhasználó státuszát 'Active'-re."""
    conn = get_db_conn()
    if not conn: return redirect(url_for('admin_list_users'))
    cursor = None
    try:
        cursor = conn.cursor()
        sql = "UPDATE Users SET MemberStatus = 'Active' WHERE UserID = ?"
        cursor.execute(sql, user_id)
        conn.commit()
        flash(f"Felhasználó (ID: {user_id}) sikeresen aktiválva.", "success")
    except pyodbc.Error as ex:
        conn.rollback()
        print(f"Hiba a felhasználó aktiválásakor (ID: {user_id}): {ex}")
        flash("Adatbázis hiba történt az aktiválás során.", "danger")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

    return redirect(url_for('admin_list_users'))
@app.route('/admin/courts')
@admin_required
def admin_list_courts():
    """Listázza az összes pályát az admin számára."""
    courts = []
    conn = get_db_conn()
    if conn:
        cursor = None
        try:
            cursor = conn.cursor()
            sql = "SELECT CourtID, CourtNumber, SurfaceType, LocationType, PricePerHour FROM Courts ORDER BY CourtNumber"
            cursor.execute(sql)
            columns = [column[0] for column in cursor.description]
            courts = [dict(zip(columns, row)) for row in cursor.fetchall()]
        except pyodbc.Error as ex:
            print(f"Hiba az admin/courts lekérdezéskor: {ex}")
            flash("Hiba történt a pályák listázása közben.", "danger")
        except Exception as e: 
             print(f"Hiba a pályák feldolgozásakor: {e}")
             flash("Hiba történt a pályák adatainak feldolgozása közben.", "danger")
        finally:
            if cursor: cursor.close()
            if conn: conn.close()
    return render_template('admin/admin_courts.html', courts=courts)

@app.route('/admin/court/add', methods=['GET'])
@admin_required
def admin_add_court():
    """Megjeleníti az új pálya hozzáadása űrlapot."""
    return render_template('admin/admin_add_court.html')

@app.route('/admin/court/create', methods=['POST'])
@admin_required
def admin_create_court():
    """Kezeli az új pálya létrehozását."""
    court_number = request.form.get('court_number')
    surface_type = request.form.get('surface_type') 
    location_type = request.form.get('location_type') 
    price_str = request.form.get('price_per_hour')

    # --- Validálás ---
    error = None
    price = None
    if not court_number: error = "Pályaszám megadása kötelező."
    if not price_str: error = "Óradíj megadása kötelező."
    else:
        try:
            price = float(price_str.replace(',', '.'))
            if price < 0: error = "Az óradíj nem lehet negatív."
        except ValueError:
            error = "Érvénytelen óradíj formátum. Csak számot adj meg (pl. 3000)."

    if error:
        flash(f"Hiba: {error}", "danger")
        return render_template('admin/admin_add_court.html') # Vissza az űrlapra

    # --- Adatbázis művelet ---
    conn = get_db_conn()
    if not conn: return redirect(url_for('admin_list_courts')) # Hiba a kapcsolatnál
    cursor = None
    try:
        cursor = conn.cursor()
        sql = """
            INSERT INTO Courts (CourtNumber, SurfaceType, LocationType, PricePerHour)
            VALUES (?, ?, ?, ?)
        """
        cursor.execute(sql, court_number, surface_type or None, location_type or None, price)
        conn.commit()
        flash(f"Pálya '{court_number}' sikeresen létrehozva.", "success")
        return redirect(url_for('admin_list_courts')) # Sikeres létrehozás után a listára

    except pyodbc.IntegrityError as ie:
        conn.rollback()
        print(f"Integrity Hiba az admin/court/create műveletnél: {ie}")
        flash(f"Hiba: A '{court_number}' pályaszám már létezik. Válassz másikat.", "danger")
    except pyodbc.Error as ex:
        conn.rollback()
        print(f"Adatbázis Hiba az admin/court/create műveletnél: {ex}")
        flash("Adatbázis hiba történt a pálya létrehozásakor.", "danger")
    except Exception as e:
        conn.rollback()
        print(f"Általános hiba az admin/court/create műveletnél: {e}")
        flash("Váratlan hiba történt a pálya létrehozásakor.", "danger")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

    return render_template('admin/admin_add_court.html')


@app.route('/admin/court/edit/<int:court_id>', methods=['GET'])
@admin_required
def admin_edit_court(court_id):
    """Megjeleníti a pálya szerkesztő űrlapot."""
    court = None
    conn = get_db_conn()
    if conn:
        cursor = None
        try:
            cursor = conn.cursor()
            sql = "SELECT CourtID, CourtNumber, SurfaceType, LocationType, PricePerHour FROM Courts WHERE CourtID = ?"
            cursor.execute(sql, court_id)
            court_raw = cursor.fetchone()
            if court_raw:
                 columns = [column[0] for column in cursor.description]
                 court = dict(zip(columns, court_raw))
            else:
                flash(f"Hiba: Nem található pálya ezzel az ID-val: {court_id}", "danger")
                return redirect(url_for('admin_list_courts'))
        except pyodbc.Error as ex:
             print(f"Hiba az admin/court/edit lekérdezéskor (ID: {court_id}): {ex}")
             flash("Hiba történt a pálya adatainak betöltésekor.", "danger")
             return redirect(url_for('admin_list_courts'))
        except Exception as e: 
             print(f"Hiba a pálya adatainak feldolgozásakor (edit): {e}")
             flash("Hiba történt a pálya adatainak feldolgozása közben.", "danger")
             return redirect(url_for('admin_list_courts'))
        finally:
            if cursor: cursor.close()
            if conn: conn.close()
    else:
         return redirect(url_for('admin_list_courts'))

    return render_template('admin/admin_edit_court.html', court=court)


@app.route('/admin/court/update', methods=['POST'])
@admin_required
def admin_update_court():
    """Kezeli a pálya adatainak frissítését."""
    court_id = request.form.get('court_id')
    court_number = request.form.get('court_number')
    surface_type = request.form.get('surface_type')
    location_type = request.form.get('location_type')
    price_str = request.form.get('price_per_hour')

    # --- Validálás ---
    error = None
    price = None
    court_id_int = None
    if not court_id: error = "Hiányzó Pálya ID."
    if not court_number: error = "Pályaszám megadása kötelező."
    if not price_str: error = "Óradíj megadása kötelező."
    else:
        try:
            price = float(price_str.replace(',', '.'))
            if price < 0: error = "Az óradíj nem lehet negatív."
            court_id_int = int(court_id) 
        except ValueError:
             error = "Érvénytelen ID vagy óradíj formátum."
        except TypeError: 
             error = "Hiányzó vagy érvénytelen Pálya ID."


    if error:
        flash(f"Hiba: {error}", "danger")
        if court_id_int:
             return redirect(url_for('admin_list_courts'))
        else:
             return redirect(url_for('admin_list_courts')) 

    # --- Adatbázis művelet ---
    conn = get_db_conn()
    if not conn: return redirect(url_for('admin_list_courts'))
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT CourtID FROM Courts WHERE CourtNumber = ? AND CourtID != ?", (court_number, court_id_int))
        existing_court = cursor.fetchone()
        if existing_court:
             flash(f"Hiba: A '{court_number}' pályaszám már létezik egy másik pályához rendelve (ID: {existing_court[0]}).", "danger")
             conn.rollback()
             return redirect(url_for('admin_edit_court', court_id=court_id_int))

        # UPDATE végrehajtása
        sql = """
            UPDATE Courts
            SET CourtNumber = ?, SurfaceType = ?, LocationType = ?, PricePerHour = ?
            WHERE CourtID = ?
        """
        cursor.execute(sql, court_number, surface_type or None, location_type or None, price, court_id_int)
        conn.commit()
        flash(f"Pálya '{court_number}' (ID: {court_id_int}) sikeresen frissítve.", "success")
        return redirect(url_for('admin_list_courts')) 

    except pyodbc.IntegrityError as ie:
        conn.rollback()
        print(f"Integrity Hiba az admin/court/update műveletnél: {ie}")
        flash(f"Hiba: A '{court_number}' pályaszám már létezik.", "danger")
    except pyodbc.Error as ex:
        conn.rollback()
        print(f"Adatbázis Hiba az admin/court/update műveletnél: {ex}")
        flash("Adatbázis hiba történt a pálya frissítésekor.", "danger")
    except Exception as e:
        conn.rollback()
        print(f"Általános hiba az admin/court/update műveletnél: {e}")
        flash("Váratlan hiba történt a pálya frissítésekor.", "danger")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

        return redirect(url_for('admin_list_courts'))


@app.route('/admin/court/delete/<int:court_id>', methods=['POST'])
@admin_required
def admin_delete_court(court_id):
    """Kezeli egy pálya törlését."""
    conn = get_db_conn()
    if not conn: return redirect(url_for('admin_list_courts'))
    cursor = None
    court_number_for_flash = f"ID: {court_id}" 
    try:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT CourtNumber FROM Courts WHERE CourtID = ?", court_id)
            court_row = cursor.fetchone()
            if court_row:
                court_number_for_flash = court_row[0]
        except Exception as e:
            print(f"Info: Nem sikerült lekérni a törlendő pálya nevét (ID: {court_id}): {e}")

        # Törlés végrehajtása
        # Ellenőrizzük, hogy van-e foglalás a pályához
        sql = "DELETE FROM Courts WHERE CourtID = ?"
        cursor.execute(sql, court_id)
        conn.commit()
        flash(f"Pálya '{court_number_for_flash}' sikeresen törölve.", "success")

    except pyodbc.IntegrityError as ie:
        conn.rollback()
        print(f"Integrity Hiba az admin/court/delete műveletnél (ID: {court_id}): {ie}")
        flash(f"Hiba: A(z) '{court_number_for_flash}' pálya nem törölhető, mert foglalások hivatkoznak rá. Először töröld a kapcsolódó foglalásokat (vagy módosítsd őket).", "danger")
    except pyodbc.Error as ex:
        conn.rollback()
        print(f"Adatbázis Hiba az admin/court/delete műveletnél (ID: {court_id}): {ex}")
        flash("Adatbázis hiba történt a pálya törlésekor.", "danger")
    except Exception as e:
        conn.rollback()
        print(f"Általános hiba az admin/court/delete műveletnél (ID: {court_id}): {e}")
        flash("Váratlan hiba történt a pálya törlésekor.", "danger")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

    # Mindig a listára irányítunk vissza
    return redirect(url_for('admin_list_courts'))

@app.route('/admin/equipment')
@admin_required
def admin_list_equipment():
    """Lists all equipment for admin management."""
    equipment_list = []
    conn = get_db_conn()
    if conn:
        cursor = None
        try:
            cursor = conn.cursor()
            sql = """
                SELECT EquipmentID, EquipmentType, Brand, Model, QuantityInStock, RentalPrice
                FROM Equipment
                ORDER BY EquipmentType, Brand, Model
            """
            cursor.execute(sql)
            columns = [column[0] for column in cursor.description]
            equipment_list = [dict(zip(columns, row)) for row in cursor.fetchall()]
        except pyodbc.Error as ex:
            print(f"Hiba az admin/equipment lekérdezéskor: {ex}")
            flash("Hiba történt az eszközök listázása közben.", "danger")
        except Exception as e:
            print(f"Hiba az eszközök feldolgozásakor: {e}")
            flash("Hiba történt az eszközök adatainak feldolgozása közben.", "danger")
        finally:
            if cursor: cursor.close()
            if conn: conn.close()
    return render_template('admin/admin_equipment.html', equipment_list=equipment_list)

@app.route('/admin/equipment/add', methods=['GET'])
@admin_required
def admin_add_equipment():
    """Displays the form to add new equipment."""
    return render_template('admin/admin_add_equipment.html')

@app.route('/admin/equipment/create', methods=['POST'])
@admin_required
def admin_create_equipment():
    """Handles the creation of new equipment."""
    e_type = request.form.get('equipment_type')
    brand = request.form.get('brand')
    model = request.form.get('model')
    quantity_str = request.form.get('quantity')
    price_str = request.form.get('price')

    error = None
    quantity = 0
    price = 0.0
    if not e_type: error = "Eszköz típusának megadása kötelező."
    if quantity_str is None: error = "Készlet megadása kötelező."
    if price_str is None: error = "Kölcsönzési díj megadása kötelező."

    if error is None: 
        try:
            quantity = int(quantity_str)
            if quantity < 0: error = "A készlet nem lehet negatív."
        except (ValueError, TypeError):
            error = "Érvénytelen készlet formátum (egész számot adj meg)."
        try:
            price = float(price_str.replace(',', '.'))
            if price < 0: error = "A kölcsönzési díj nem lehet negatív."
        except (ValueError, TypeError):
            error = (error + " " if error else "") + "Érvénytelen díj formátum (számot adj meg)."

    if error:
        flash(f"Hiba: {error}", "danger")
        return render_template('admin/admin_add_equipment.html')

    # --- Adatbázis ---
    conn = get_db_conn()
    if not conn: return redirect(url_for('admin_list_equipment'))
    cursor = None
    try:
        cursor = conn.cursor()
        sql = """
            INSERT INTO Equipment (EquipmentType, Brand, Model, QuantityInStock, RentalPrice)
            VALUES (?, ?, ?, ?, ?)
        """
        cursor.execute(sql, e_type, brand or None, model or None, quantity, price)
        conn.commit()
        flash(f"Eszköz '{e_type} {brand or ''}' sikeresen létrehozva.", "success")
        return redirect(url_for('admin_list_equipment'))

    except pyodbc.Error as ex: 
        conn.rollback()
        print(f"Adatbázis Hiba az admin/equipment/create műveletnél: {ex}")
        flash("Adatbázis hiba történt az eszköz létrehozásakor.", "danger")
    except Exception as e:
        conn.rollback()
        print(f"Általános hiba az admin/equipment/create műveletnél: {e}")
        flash("Váratlan hiba történt az eszköz létrehozásakor.", "danger")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

    return render_template('admin/admin_add_equipment.html')


@app.route('/admin/equipment/edit/<int:equipment_id>', methods=['GET'])
@admin_required
def admin_edit_equipment(equipment_id):
    """Displays the form to edit existing equipment."""
    item = None
    conn = get_db_conn()
    if conn:
        cursor = None
        try:
            cursor = conn.cursor()
            sql = "SELECT EquipmentID, EquipmentType, Brand, Model, QuantityInStock, RentalPrice FROM Equipment WHERE EquipmentID = ?"
            cursor.execute(sql, equipment_id)
            item_raw = cursor.fetchone()
            if item_raw:
                 columns = [column[0] for column in cursor.description]
                 item = dict(zip(columns, item_raw))
            else:
                flash(f"Hiba: Nem található eszköz ezzel az ID-val: {equipment_id}", "danger")
                return redirect(url_for('admin_list_equipment'))
        except pyodbc.Error as ex:
             print(f"Hiba az admin/equipment/edit lekérdezéskor (ID: {equipment_id}): {ex}")
             flash("Hiba történt az eszköz adatainak betöltésekor.", "danger")
             return redirect(url_for('admin_list_equipment'))
        except Exception as e:
             print(f"Hiba az eszköz adatainak feldolgozásakor (edit): {e}")
             flash("Hiba történt az eszköz adatainak feldolgozása közben.", "danger")
             return redirect(url_for('admin_list_equipment'))
        finally:
            if cursor: cursor.close()
            if conn: conn.close()
    else:
         return redirect(url_for('admin_list_equipment'))

    return render_template('admin/admin_edit_equipment.html', item=item)


@app.route('/admin/equipment/update', methods=['POST'])
@admin_required
def admin_update_equipment():
    """Handles the update of existing equipment."""
    equipment_id = request.form.get('equipment_id')
    e_type = request.form.get('equipment_type')
    brand = request.form.get('brand')
    model = request.form.get('model')
    quantity_str = request.form.get('quantity')
    price_str = request.form.get('price')

    error = None
    quantity = 0
    price = 0.0
    equipment_id_int = None

    if not equipment_id: error = "Hiányzó Eszköz ID."
    if not e_type: error = "Eszköz típusának megadása kötelező."
    if quantity_str is None: error = "Készlet megadása kötelező."
    if price_str is None: error = "Kölcsönzési díj megadása kötelező."

    if error is None:
        try:
            equipment_id_int = int(equipment_id)
        except (ValueError, TypeError):
            error = "Érvénytelen Eszköz ID."
        try:
            quantity = int(quantity_str)
            if quantity < 0: error = "A készlet nem lehet negatív."
        except (ValueError, TypeError):
             error = (error + " " if error else "") + "Érvénytelen készlet formátum."
        try:
            price = float(price_str.replace(',', '.'))
            if price < 0: error = "A kölcsönzési díj nem lehet negatív."
        except (ValueError, TypeError):
             error = (error + " " if error else "") + "Érvénytelen díj formátum."

    if error:
        flash(f"Hiba: {error}", "danger")
        if equipment_id_int:
            return redirect(url_for('admin_edit_equipment', equipment_id=equipment_id_int))
        else:
            return redirect(url_for('admin_list_equipment')) 

    conn = get_db_conn()
    if not conn: return redirect(url_for('admin_list_equipment'))
    cursor = None
    try:
        cursor = conn.cursor()
        sql = """
            UPDATE Equipment
            SET EquipmentType = ?, Brand = ?, Model = ?, QuantityInStock = ?, RentalPrice = ?
            WHERE EquipmentID = ?
        """
        cursor.execute(sql, e_type, brand or None, model or None, quantity, price, equipment_id_int)
        conn.commit()
        flash(f"Eszköz '{e_type} {brand or ''}' (ID: {equipment_id_int}) sikeresen frissítve.", "success")
        return redirect(url_for('admin_list_equipment'))

    except pyodbc.Error as ex:
        conn.rollback()
        print(f"Adatbázis Hiba az admin/equipment/update műveletnél: {ex}")
        flash("Adatbázis hiba történt az eszköz frissítésekor.", "danger")
    except Exception as e:
        conn.rollback()
        print(f"Általános hiba az admin/equipment/update műveletnél: {e}")
        flash("Váratlan hiba történt az eszköz frissítésekor.", "danger")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

    return redirect(url_for('admin_edit_equipment', equipment_id=equipment_id_int))


@app.route('/admin/equipment/delete/<int:equipment_id>', methods=['POST'])
@admin_required
def admin_delete_equipment(equipment_id):
    """Handles the deletion of equipment."""
    conn = get_db_conn()
    if not conn: return redirect(url_for('admin_list_equipment'))
    cursor = None
    item_name_for_flash = f"ID: {equipment_id}"
    try:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT EquipmentType, Brand FROM Equipment WHERE EquipmentID = ?", equipment_id)
            item_row = cursor.fetchone()
            if item_row:
                 item_name_for_flash = f"{item_row[0]} {item_row[1] or ''}".strip()
        except Exception as e:
            print(f"Info: Nem sikerült lekérni a törlendő eszköz nevét (ID: {equipment_id}): {e}")

        sql = "DELETE FROM Equipment WHERE EquipmentID = ?"
        cursor.execute(sql, equipment_id)
        conn.commit()
        flash(f"Eszköz '{item_name_for_flash}' sikeresen törölve.", "success")

    except pyodbc.IntegrityError as ie:
        conn.rollback()
        print(f"Integrity Hiba az admin/equipment/delete műveletnél (ID: {equipment_id}): {ie}")
        flash(f"Hiba: Az eszköz '{item_name_for_flash}' nem törölhető, mert aktív kölcsönzések hivatkoznak rá.", "danger")
    except pyodbc.Error as ex:
        conn.rollback()
        print(f"Adatbázis Hiba az admin/equipment/delete műveletnél (ID: {equipment_id}): {ex}")
        flash("Adatbázis hiba történt az eszköz törlésekor.", "danger")
    except Exception as e:
        conn.rollback()
        print(f"Általános hiba az admin/equipment/delete műveletnél (ID: {equipment_id}): {e}")
        flash("Váratlan hiba történt az eszköz törlésekor.", "danger")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

    return redirect(url_for('admin_list_equipment'))
@app.route('/admin/bookings')
@admin_required
def admin_list_bookings():
    """Lists bookings for admin view, default: future confirmed."""
    bookings = []
    conn = get_db_conn()
    if conn:
        cursor = None
        try:
            cursor = conn.cursor()
            sql = """
                SELECT
                    b.BookingID, b.StartTime, b.EndTime, b.BookingStatus, b.UserID,
                    u.Name AS UserName,
                    c.CourtNumber, c.CourtID
                FROM CourtBookings b
                JOIN Users u ON b.UserID = u.UserID
                JOIN Courts c ON b.CourtID = c.CourtID
                WHERE b.EndTime >= GETDATE() -- Show future or ongoing bookings
                  AND b.BookingStatus IN ('Confirmed', 'Pending') -- Filter relevant statuses
                ORDER BY b.StartTime ASC;
            """
            cursor.execute(sql)
            columns = [column[0] for column in cursor.description]
            bookings = [dict(zip(columns, row)) for row in cursor.fetchall()]

        except pyodbc.Error as ex:
            print(f"Hiba az admin/bookings lekérdezéskor: {ex}")
            flash("Hiba történt a foglalások listázása közben.", "danger")
        except Exception as e:
            print(f"Hiba a foglalások feldolgozásakor: {e}")
            flash("Hiba történt a foglalások adatainak feldolgozása közben.", "danger")
        finally:
            if cursor: cursor.close()
            if conn: conn.close()

    return render_template('admin/admin_bookings.html', bookings=bookings)


@app.route('/admin/booking/cancel/<int:booking_id>', methods=['POST'])
@admin_required
def admin_cancel_booking(booking_id):
    """Handles booking cancellation initiated by an admin."""
    admin_user_id = session.get('user_id') 

    conn = get_db_conn()
    if not conn:
        flash("Adatbázis kapcsolati hiba.", "danger")
        return redirect(url_for('admin_list_bookings'))

    cursor = None
    final_status_message = "Ismeretlen hiba történt a lemondás során."
    flash_category = "danger"

    try:
        cursor = conn.cursor()
        sql_cancel = """
            DECLARE @CancelStatusMessage_Out NVARCHAR(255) = N'';
            EXEC sp_CancelBooking @BookingID = ?, @UserID = ?, @IsAdminAction = ?, @StatusMessage = @CancelStatusMessage_Out OUTPUT;
            SELECT @CancelStatusMessage_Out AS FinalStatusMessage;
        """
        params_cancel = (booking_id, admin_user_id, 1)
        cursor.execute(sql_cancel, params_cancel)
        result_cancel = cursor.fetchone()

        if result_cancel:
            final_status_message = result_cancel[0]
            if "HIBA" not in final_status_message and "nem törölhető" not in final_status_message: 
                flash_category = "success"
                conn.commit() 
                print(f"Admin (ID:{admin_user_id}) sikeresen lemondta a foglalást (ID:{booking_id}).")
            else:
                flash_category = "warning" 
                conn.rollback()
                print(f"Admin lemondás (ID:{booking_id}) sikertelen vagy információ: {final_status_message}")
        else:
             final_status_message = "Hiba: A lemondó eljárás nem adott vissza üzenetet."
             conn.rollback() 
             print(f"Admin lemondás (ID:{booking_id}) sikertelen: SP nem adott vissza üzenetet.")

    except pyodbc.Error as db_ex:
        print(f"Adatbázis hiba az admin lemondás során (BookingID: {booking_id}): {db_ex}")
        final_status_message = "Adatbázis hiba történt a lemondás során."
        flash_category = "danger"
        try:
            if conn: conn.rollback()
        except Exception as rb_ex_db: print(f"Rollback hiba (DB Exception): {rb_ex_db}")
    except Exception as e:
        print(f"Általános hiba az admin lemondás során (BookingID: {booking_id}): {e}")
        final_status_message = f"Általános hiba a lemondás során: {e}"
        flash_category = "danger"
        try:
            if conn: conn.rollback()
        except Exception as rb_ex_gen: print(f"Rollback hiba (General Exception): {rb_ex_gen}")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
        print(f"Adatbázis kapcsolat lezárva (/admin/booking/cancel, BookingID: {booking_id}).")

    flash(final_status_message, flash_category)
    return redirect(url_for('admin_list_bookings'))
@app.route('/profile/edit', methods=['GET'])
def edit_profile():
    """Megjeleníti a profil szerkesztő űrlapot."""
    if 'user_id' not in session:
        flash("A profil szerkesztéséhez be kell jelentkezni!", "warning")
        return redirect(url_for('login'))

    user_id = session['user_id']
    current_user_data = None

    conn = get_db_conn()
    if conn:
        cursor = None
        try:
            cursor = conn.cursor()
        
            sql = "SELECT Name, Email FROM Users WHERE UserID = ?"
            cursor.execute(sql, user_id)
            user_raw = cursor.fetchone()
            if user_raw:
           
                 try:
                    columns = [column[0] for column in cursor.description]
                    current_user_data = dict(zip(columns, user_raw))
                 except Exception as e:
                     print(f"Hiba a profil szerkesztési adatok szótárrá alakításakor: {e}")
                     flash("Hiba történt az adatok feldolgozása közben.", "danger")
            else:
                flash("Hiba: Felhasználói adatok nem találhatók.", "danger")
                session.clear() 
                return redirect(url_for('login'))
        except pyodbc.Error as ex:
            print(f"Hiba a profil szerkesztési adatok lekérdezésekor (UserID: {user_id}): {ex}")
            flash("Adatbázis hiba történt a profiladatok lekérdezésekor.", "danger")
        finally:
            if cursor: cursor.close()
            if conn: conn.close()
    return render_template('edit_profile.html', current_user_data=current_user_data)


@app.route('/profile/update', methods=['POST'])
def update_profile():
    """Kezeli a profil szerkesztő űrlap elküldését."""
    if 'user_id' not in session:
        flash("A profil frissítéséhez be kell jelentkezni!", "warning")
        return redirect(url_for('login'))

    user_id = session['user_id']
    name = request.form.get('name')
    email = request.form.get('email')

    # --- Validálás ---
    error = None
    if not name: error = "Név megadása kötelező."
    if not email: error = "Email cím megadása kötelező."

    if error:
        flash(f"Hiba: {error}", "danger")
        return redirect(url_for('edit_profile'))

    # --- Adatbázis művelet ---
    conn = get_db_conn()
    if not conn: return redirect(url_for('profile')) 
    cursor = None
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT Email FROM Users WHERE UserID = ?", user_id)
        current_email_row = cursor.fetchone()
        current_email = current_email_row[0] if current_email_row else None

        if current_email is not None and email != current_email:
            cursor.execute("SELECT UserID FROM Users WHERE Email = ? AND UserID != ?", (email, user_id))
            existing_user = cursor.fetchone()
            if existing_user:
                 flash(f"Hiba: Az '{email}' email cím már foglalt egy másik felhasználó által. Válassz másikat!", "danger")
                 conn.rollback()
                 return redirect(url_for('edit_profile')) 

        sql_update = "UPDATE Users SET Name = ?, Email = ? WHERE UserID = ?"
        cursor.execute(sql_update, name, email, user_id)
        conn.commit()

        session['user_name'] = name 
        flash("Profil sikeresen frissítve!", "success")
        return redirect(url_for('profile'))

    except pyodbc.Error as ex:
        conn.rollback()
        print(f"Adatbázis hiba a profil frissítésekor (UserID: {user_id}): {ex}")
        flash("Adatbázis hiba történt a profil frissítésekor.", "danger")
        return redirect(url_for('profile')) 
        # ================================
    except Exception as e:
        conn.rollback()
        print(f"Általános hiba a profil frissítésekor (UserID: {user_id}): {e}")
        flash("Váratlan hiba történt a profil frissítésekor.", "danger")
        return redirect(url_for('profile')) 
        # ================================
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route('/profile/change_password', methods=['GET'])
def change_password():
    """Displays the change password form."""
    if 'user_id' not in session:
        flash("A jelszó módosításához be kell jelentkezni!", "warning")
        return redirect(url_for('login'))
    return render_template('change_password.html', form_data=request.form)


@app.route('/profile/update_password', methods=['POST'])
def update_password():
    """Handles the change password form submission."""
    if 'user_id' not in session:
        flash("A jelszó frissítéséhez be kell jelentkezni!", "warning")
        return redirect(url_for('login'))

    user_id = session['user_id']
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')

    error = None
    if not current_password: error = "Jelenlegi jelszó megadása kötelező."
    elif not new_password: error = "Új jelszó megadása kötelező."
    elif not confirm_password: error = "Új jelszó megerősítése kötelező."
    elif new_password != confirm_password: error = "Az új jelszó és a megerősítés nem egyezik."
    elif len(new_password) < 3: error = "Az új jelszónak legalább 3 karakter hosszúnak kell lennie." 

    if error:
        flash(f"Hiba: {error}", "danger")
        return redirect(url_for('change_password'))

    conn = get_db_conn()
    if not conn: return redirect(url_for('profile')) 
    cursor = None
    try:
        cursor = conn.cursor()

        sql_get_hash = "SELECT PasswordHash FROM Users WHERE UserID = ?"
        cursor.execute(sql_get_hash, user_id)
        user_row = cursor.fetchone()

        if not user_row:
             flash("Hiba: Felhasználó nem található (ez nem fordulhatna elő).", "danger")
             conn.rollback() 
             return redirect(url_for('profile'))

        current_hash = user_row[0] 

        if not check_password_hash(current_hash, current_password):
             flash("Hiba: A megadott jelenlegi jelszó helytelen.", "danger")
             conn.rollback()
             return redirect(url_for('change_password'))

        if check_password_hash(current_hash, new_password):
             flash("Az új jelszó nem lehet ugyanaz, mint a régi.", "warning")
             conn.rollback()
             return redirect(url_for('change_password'))

        new_hash = generate_password_hash(new_password)

        sql_update_hash = "UPDATE Users SET PasswordHash = ? WHERE UserID = ?"
        cursor.execute(sql_update_hash, new_hash, user_id)
        conn.commit()

        flash("Jelszó sikeresen módosítva!", "success")
        return redirect(url_for('profile')) 

    except pyodbc.Error as ex:
        conn.rollback()
        print(f"Adatbázis hiba a jelszó frissítésekor (UserID: {user_id}): {ex}")
        flash("Adatbázis hiba történt a jelszó frissítésekor.", "danger")
    except Exception as e:
        conn.rollback()
        print(f"Általános hiba a jelszó frissítésekor (UserID: {user_id}): {e}")
        flash("Váratlan hiba történt a jelszó frissítésekor.", "danger")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

    return redirect(url_for('change_password'))
    return redirect(url_for('profile'))

if __name__ == '__main__':
   
    app.run(debug=True, host='0.0.0.0', port=5000)