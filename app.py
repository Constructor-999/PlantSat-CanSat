from flask import Flask, render_template, send_file
from threading import Lock
from flask_socketio import SocketIO, emit
import struct
import pandas as pd
from sklearn import linear_model
import numpy as np
import pvlib 
import datetime 
import geopy.distance
import math
from pyrf24 import RF24, RF24Network, RF24_2MBPS
import board
from adafruit_ms8607 import MS8607
from gpiozero import AngularServo

i2c = board.I2C()  
sensor = MS8607(i2c)

async_mode = None
baseCoords = (46.812925, 6.943250)
baseCoordX, baseCoordY = baseCoords
OCoords = (46.620477, 6.435002)
OCoordX, OCoordY = OCoords

THIS_NODE = 0o0

app = Flask(__name__, template_folder="templates")
socketio = SocketIO(app, async_mode=async_mode)
thread = None
thread_lock = Lock()

radio = RF24(22, 0)
network = RF24Network(radio)

if not radio.begin():
    raise OSError("nRF24L01 hardware isn't responding")
radio.channel = 90
radio.data_rate = RF24_2MBPS
network.begin(THIS_NODE)
radio.print_pretty_details()

def get_sec(h,m,s):
    return int(h) * 3600 + int(m) * 60 + int(s)

def fromSec(s):
    hours = s // 3600 
    s = s - (hours * 3600)
    minutes = s // 60
    seconds = s - (minutes * 60)
    return '{:02}-{:02}-{:02}'.format(int(hours), int(minutes), int(seconds))

ServoH = AngularServo(24, initial_angle=0, min_angle=-90, max_angle=90, min_pulse_width=0.5/1000, max_pulse_width=2.5/1000, frame_width=20/1000)
ServoB = AngularServo(25, initial_angle=0, min_angle=-90, max_angle=90, min_pulse_width=0.5/1000, max_pulse_width=2.5/1000, frame_width=20/1000)

def nrf_recever_thread():
    while True:
        baseHeight = round(pvlib.atmosphere.pres2alt(round(sensor.pressure, 2) * 100), 2)
        network.update()
        while network.available():
            header, payload = network.read()
            nowDate = datetime.datetime.now()
            print(["{:02x}".format(c) for c in payload][:8])
            if ["{:02x}".format(c) for c in payload][:8] == ['89', '50', '4e', '47', '0d', '0a', '1a', '0a']:
                res_img = open(f'./data/{nowDate.month}-{nowDate.day}-{nowDate.hour}-{nowDate.minute}-{nowDate.second}.png', "wb")
                while True:
                    network.update()
                    if network.available():
                        header, imgpayload = network.read()
                        res_img.write(imgpayload)
                        if ["{:02x}".format(c) for c in imgpayload][-2:] == ['60', '82']:
                            socketio.emit("img", {"name": f'{nowDate.month}-{nowDate.day}-{nowDate.hour}-{nowDate.minute}-{nowDate.second}.png'})
                            break
            try:
                canRes = struct.unpack("<Bfffffif", payload)
                R = 6371

                xCan = R * math.cos(round(canRes[1], 8)) * math.cos(round(canRes[2], 8))
                yCan = R * math.cos(round(canRes[1], 8)) * math.sin(round(canRes[2], 8))
                zCan = R * math.sin(round(canRes[1], 8))

                xBase = R * math.cos(baseCoordX) * math.cos(baseCoordY)
                yBase = R * math.cos(baseCoordX) * math.sin(baseCoordY)
                zBase = R * math.sin(baseCoordX)

                xO = R * math.cos(OCoordX) * math.cos(OCoordY)
                yO = R * math.cos(OCoordX) * math.sin(OCoordY)
                zO = R * math.sin(OCoordX)

                distOBase = math.dist((xO, yO), (xBase, yBase))
                distCanBase = math.dist((xCan, yCan), (xBase, yBase))
                distOCan = math.dist((xO, yO), (xCan, yCan))

                angleCanBase = math.degrees(math.acos((distCanBase**2 + distOBase**2 - distOCan**2 )/(2 * distCanBase * distOBase)))
                angleCanHeight = math.degrees(math.atan((round(pvlib.atmosphere.pres2alt(round(canRes[3], 2) * 100), 2) - baseHeight)/distCanBase))

                ServoH.angle = angleCanBase
                ServoB.angle = angleCanHeight

                socketio.emit("can_logs", 
                            { "latitude": round(canRes[1], 8), 
                             "longitude": round(canRes[2], 8), 
                             "pressure": round(canRes[3], 2),
                             "height": round(pvlib.atmosphere.pres2alt(round(canRes[3], 2) * 100), 2),
                             "temperature": round(canRes[4], 2), 
                             "humidity": round(canRes[5], 2), 
                             "CO2": canRes[6],
                             "O2": round(canRes[7], 2),
                             "heure": f'{nowDate.month}-{nowDate.day}-{nowDate.hour}-{nowDate.minute}-{nowDate.second}',
                             "vertical": round(angleCanHeight, 2),
                             "horizontal": round(angleCanBase, 2)})
                canDF = pd.DataFrame(
                     {"s": [f'{get_sec(nowDate.hour, nowDate.minute, nowDate.second)}'],
                     "time": [f'{nowDate.month}-{nowDate.day}-{nowDate.hour}-{nowDate.minute}-{nowDate.second}'],
                     "latitude": [round(canRes[1], 8)], 
                     "longitude": [round(canRes[2], 8)], 
                     "pressure": [round(canRes[3], 2)],
                     "height": [round(pvlib.atmosphere.pres2alt(round(canRes[3], 2) * 100), 2)],
                     "temperature": [round(canRes[4], 2)], 
                     "humidity": [round(canRes[5], 2)], 
                     "CO2": [canRes[6]],
                     "O2": [round(canRes[7], 2)]})
                canDF.to_csv("./data/PlantSatLogs.csv", mode="a", index=False, header=False)
            except struct.error:
                 print("err")
@app.route('/')
def index():
    return render_template('page.html', async_mode=socketio.async_mode)

@socketio.on('getCSVdata')
def getData():
    emit('ChartData', {"labels": pd.read_csv("./data/PlantSatLogs.csv")["time"].tolist(), "data": pd.read_csv("./data/PlantSatLogs.csv")["height"].tolist()})

@socketio.on("clearCSV")
def delData():
    pd.DataFrame({"s": [], "time": [],"latitude": [], "longitude": [], "pressure": [],"height": [],"temperature": [], "humidity": [], "CO2": [],"O2": []}).to_csv("./data/PlantSatLogs.csv", mode="w", index=False, header=True)

@socketio.on('clearPred')
def delPred():
    pd.DataFrame({"predH": [], "predLat": [], "predLong": [], "predTime": []}).to_csv("./data/predictions.csv", mode="w", index=False, header=True)

@app.route('/CSVdownload')
def plot_csv():
    return send_file(
        'data/PlantSatLogs.csv',
        mimetype='text/csv',
        download_name='PlantSatLogs.csv',
        as_attachment=True
    )

@socketio.on('predPOS')
def calcPOS():
    for ind in range(1, len(pd.read_csv("./data/PlantSatLogs.csv")["height"].tolist())-1):
        if (pd.read_csv("./data/PlantSatLogs.csv")["height"].tolist()[ind -1] - 5) > pd.read_csv("./data/PlantSatLogs.csv")["height"].tolist()[ind]:
            CSVdata = pd.read_csv("./data/PlantSatLogs.csv", index_col=False, header=0)
            regrS = linear_model.LinearRegression()
            regrX = linear_model.LinearRegression()
            regrY = linear_model.LinearRegression()
            regrZ = linear_model.LinearRegression()

            latY = CSVdata.latitude.values[ind:]
            longY = CSVdata.longitude.values[ind:]
            xHeight = CSVdata.height.values[ind:]
            timeS = CSVdata.s.values[ind:]

            latY = latY.reshape(len(CSVdata.latitude.values[ind:]), 1)
            longY = longY.reshape(len(CSVdata.longitude.values[ind:]), 1)
            xHeight = xHeight.reshape(len(CSVdata.height.values[ind:]), 1)
            timeS = timeS.reshape(len(CSVdata.s.values[ind:]), 1)

            canX = []
            canY = []
            canZ = []
            R = 6371

            for nb in range(0, latY.size -1):
                canX.append(R * math.cos(latY[nb]) * math.cos(longY[nb]))
                canY.append(R * math.cos(latY[nb]) * math.sin(longY[nb]))
                canZ.append(R * math.sin(latY[nb]))

            
            regrX.fit(xHeight, canX)
            regrY.fit(xHeight, canY)
            regrZ.fit(xHeight, canZ)
            regrS.fit(xHeight, timeS)

            predX = np.array(regrX.predict(xHeight)).astype(float)
            predY = np.array(regrY.predict(xHeight)).astype(float)
            predZ = np.array(regrZ.predict(xHeight)).astype(float)
            predSec = np.array(regrS.predict(xHeight)).astype(int)

            aX = (predX.tolist()[0][0] - predX.tolist()[-1][0]) / (xHeight.tolist()[0][0] - xHeight.tolist()[-1][0])
            bX = predX.tolist()[0][0] - (aX * xHeight.tolist()[0][0])

            aY = (predY.tolist()[0][0] - predY.tolist()[-1][0]) / (xHeight.tolist()[0][0] - xHeight.tolist()[-1][0])
            bY = predY.tolist()[0][0] - (aY * xHeight.tolist()[0][0])

            aZ = (predZ.tolist()[0][0] - predZ.tolist()[-1][0]) / (xHeight.tolist()[0][0] - xHeight.tolist()[-1][0])
            bZ = predZ.tolist()[0][0] - (aZ * xHeight.tolist()[0][0])

            aS = (predSec.tolist()[0][0] - predSec.tolist()[-1][0]) / (xHeight.tolist()[0][0] - xHeight.tolist()[-1][0])
            bS = predSec.tolist()[0][0] - (aS * xHeight.tolist()[0][0])

            predlat = math.asin((aZ * 0 + bZ) / R)
            predlong = math.atan2((aY * 0 + bY), (aX * 0 + bX))
            
            pd.DataFrame({"predH": [0], "predLat": [predlat], "predLong": [predlong], "predTime": [f'{fromSec(round(aS * 0 + bS, 0))}']}).to_csv("./data/predictions.csv", mode="a", index=False, header=False)
            emit("resPred", {"hasInfos": True ,"point": {"X": f'{datetime.datetime.now().month}-{datetime.datetime.now().day}-{fromSec(round(aS * 0 + bS, 0))}', "Y": '0'}, "label": f'Prediction {pd.read_csv("./data/predictions.csv", index_col=False, header=0).predTime.values.size}', "predLat": f'{predlat}', "predLong": f'{predlong}'})
            break

@socketio.event
def connect():
    global thread
    with thread_lock:
        if thread is None:
            thread = socketio.start_background_task(nrf_recever_thread)
    emit('ChartData', {"labels": pd.read_csv("./data/PlantSatLogs.csv")["time"].tolist(), 
                       "data": pd.read_csv("./data/PlantSatLogs.csv")["height"].tolist(), 
                       "predH": pd.read_csv("./data/predictions.csv")["predH"].tolist(), 
                       "predLat": pd.read_csv("./data/predictions.csv")["predLat"].tolist(), 
                       "predLong": pd.read_csv("./data/predictions.csv")["predLong"].tolist(), 
                       "predTime": pd.read_csv("./data/predictions.csv")["predTime"].tolist()})

if __name__ == "__main__":
    try:
        socketio.run(app, "0.0.0.0", 8080)
    except KeyboardInterrupt:
        radio.power = False
        print("Powering down radio and exiting.")