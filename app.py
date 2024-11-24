from flask import Flask, render_template, request, jsonify, Response
from SRT import SRT
import requests
from datetime import datetime
import time
import threading
import queue
import os
import logging
import configparser
import io

app = Flask(__name__)

def get_config(key, default=None):
    config = configparser.ConfigParser()
    config_file = '/share/srt/app.conf'
    if os.path.exists(config_file):
        config.read(config_file)
        try:
            return config.get('DEFAULT', key)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default
    else:
        logging.error(f"설정 파일을 찾을 수 없습니다: {config_file}")
        return default

global messages, stop_reservation, output_queue
messages = []
stop_reservation = False
output_queue = queue.Queue()

# 설정 값 가져오기
SRT_ID = get_config('srt_id', '')
SRT_PASSWORD = get_config('srt_password', '')
TELEGRAM_BOT_TOKEN = get_config('telegram_bot_token', '')
TELEGRAM_CHAT_ID = get_config('telegram_chat_id', '')
PHONE_NUMBER = get_config('phone_number', '')

def send_telegram_message(bot_token, chat_id, message):
    if bot_token and chat_id:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": 'SRTrain Rev \n' + message + ' \n@' + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            logging.info("메시지가 성공적으로 전송되었습니다.")
        else:
            logging.error(f"메시지 전송에 실패했습니다. 상태 코드: {response.status_code}")

def attempt_reservation(sid, spw, dep_station, arr_station, date, time_start, time_end, phone_number, enable_telegram, bot_token, chat_id):
    global messages, stop_reservation
    try:
        srt = SRT(sid, spw, verbose=False)
        while not stop_reservation:
            try:
                message = '예약시도.....' + ' @' + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                logging.info(message)
                output_queue.put(message)
                time.sleep(1)
                
                trains = srt.search_train(dep_station, arr_station, date, time_start, time_end, available_only=False)
                if 'Expecting value' in str(trains):
                    message = 'Expecting value 오류'
                    logging.error(message)
                    output_queue.put(message)
                    messages.append(message)
                    continue
                
                for train in trains:
                    logging.info(str(train))
                    output_queue.put(str(train))
                
                for train in trains:
                    if stop_reservation:
                        break
                    try:
                        srt.reserve_standby(train)
                        srt.reserve_standby_option_settings(phone_number, True, True)
                        success_message = f"SRT 예약 대기 완료 {train}"
                        messages.append(success_message)
                        output_queue.put(success_message)
                        if enable_telegram:
                            send_telegram_message(bot_token, chat_id, success_message)
                        logging.info("예약 성공했지만 계속 진행합니다.")
                        break
                    except Exception as e:
                        error_message = f"열차 {train}에 대한 오류 발생: {e}"
                        logging.error(error_message)
                        output_queue.put(error_message)
                        messages.append(error_message)
            except Exception as e:
                error_message = f"메인 루프에서 오류 발생: {e}"
                logging.error(error_message)
                output_queue.put(error_message)
                messages.append(error_message)
                if '사용자가 많아 접속이 원활하지 않습니다.' in str(e):
                    time.sleep(5)
                    srt = SRT(sid, spw, verbose=False)
                    continue
                if enable_telegram:
                    send_telegram_message(bot_token, chat_id, error_message)
                time.sleep(5)
                srt = SRT(sid, spw, verbose=False)
    except Exception as main_e:
        critical_error = f"심각한 오류 발생: {main_e}"
        logging.critical(critical_error)
        output_queue.put(critical_error)
        messages.append(critical_error)
        if enable_telegram:
            send_telegram_message(bot_token, chat_id, critical_error)
        time.sleep(30)
        srt = SRT(sid, spw, verbose=True)
    finally:
        stop_reservation = False
        if 'srt' in locals():
            srt.logout()
    return messages

reservation_thread = None

@app.route('/', methods=['GET', 'POST'])
def index():
    global reservation_thread, stop_reservation
    if request.method == 'POST':
        if reservation_thread and reservation_thread.is_alive():
            return jsonify({'message': '이미 예약 프로세스가 실행 중입니다.'})
        stop_reservation = False
        sid = request.form.get('sid', SRT_ID)
        spw = request.form.get('spw', SRT_PASSWORD)
        dep_station = request.form['dep_station']
        arr_station = request.form['arr_station']
        if dep_station == "direct":
            dep_station = request.form['customDepStation']
        if arr_station == "direct":
            arr_station = request.form['customArrStation']
        date = request.form['date'].replace("-", "")
        start_time = f"{request.form['start_hour']}{request.form['start_minute']}00"
        end_time = f"{request.form['end_hour']}{request.form['end_minute']}00"
        phone_number = f"{request.form['phone_part1']}-{request.form['phone_part2']}-{request.form['phone_part3']}"
        enable_telegram = 'enable_telegram' in request.form
        bot_token = request.form.get('bot_token', TELEGRAM_BOT_TOKEN)
        chat_id = request.form.get('chat_id', TELEGRAM_CHAT_ID)
        reservation_thread = threading.Thread(target=attempt_reservation, args=(sid, spw, dep_station, arr_station, date, start_time, end_time, phone_number, enable_telegram, bot_token, chat_id))
        reservation_thread.start()
        return jsonify({'message': '예약 프로세스가 시작되었습니다.'})
    
    default_values = {
        'srt_id': SRT_ID,
        'srt_password': SRT_PASSWORD,
        'telegram_bot_token': TELEGRAM_BOT_TOKEN,
        'telegram_chat_id': TELEGRAM_CHAT_ID,
        'phone_number': PHONE_NUMBER
    }
    return render_template('index.html', **default_values)

@app.route('/stop', methods=['POST'])
def stop():
    global stop_reservation
    stop_reservation = True
    if 'srt' in globals():
        srt.logout()
    return jsonify({'message': '예약 프로세스가 중단되었습니다.'})

@app.route('/stream')
def stream():
    def generate():
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        formatter = logging.Formatter('%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        handler.setFormatter(formatter)
        logging.getLogger().addHandler(handler)
        last_timestamp = datetime.now()

        while True:
            log_stream.seek(0)
            log_content = log_stream.read()
            log_stream.truncate(0)
            log_stream.seek(0)

            if log_content:
                log_lines = log_content.strip().split('\n')
                new_logs = []
                for line in log_lines:
                    try:
                        timestamp_str = line.split(' - ')[0]
                        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S.%f')
                        if timestamp > last_timestamp:
                            new_logs.append(line)
                            last_timestamp = timestamp
                    except (ValueError, IndexError):
                        continue  # 잘못된 형식의 로그 라인은 무시

                if new_logs:
                    new_logs.reverse()
                    newline = '\n'
                    yield f"data: {newline.join(new_logs)}\n\n"
            else:
                time.sleep(0.1)  # 0.1초마다 확인

    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    log_level = get_config('LOG_LEVEL', 'INFO').upper()
    logging.basicConfig(
        format='%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=getattr(logging, log_level)
    )
    logger = logging.getLogger(__name__)
    try:
        port = int(get_config('PORT', 5000))
        logger.info(f"Starting SRT application on port {port}")
        app.run(host='0.0.0.0', port=port)
    except Exception as e:
        logger.error(f"Error starting application: {e}")
    while True:
        time.sleep(30)