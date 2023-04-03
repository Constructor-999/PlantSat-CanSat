from gpiozero import AngularServo
import board
import busio
from adafruit_ms8607 import MS8607
import struct
from pyrf24 import RF24, RF24Network, RF24NetworkHeader, RF24_2MBPS
import time
from picamera import PiCamera
import adafruit_scd4x
import neopixel
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import RPi.GPIO as GPIO
import serial
import pynmea2
import pvlib
from multiprocessing import Process
import math
import datetime
import os

i2c = board.I2C()
i2ads = busio.I2C(board.SCL, board.SDA)
led = neopixel.NeoPixel(board.D18, 1, brightness=0.2)
ads = ADS.ADS1115(i2ads, address=0x49)
ads.gain = 2
multiplier = 0.0625
calMV = 0
GPIO.setmode(GPIO.BCM)
Trig = 23
Echo = 24
GPIO.setup(Trig,GPIO.OUT)
GPIO.setup(Echo,GPIO.IN)
GPIO.output(Trig, False)
GPS = serial.Serial("/dev/ttyS0", 9600, timeout=0.5)
ms8607sensor = MS8607(i2c)
scd40 = adafruit_scd4x.SCD4X(i2c)
cam = PiCamera()
cam.resolution = (1920, 1080)
cam.iso = 500
cam.shutter_speed = 2000
os.system("python3 neg90.py")

fall: bool = False
latitude: float
longitude: float
o2: float
co2: int = 0
minutes: int = 1

def blink(pixel, nb, interval, color):
	for i in range(1,nb):
		pixel[0] = (0, 0, 0)
		time.sleep(interval)
		pixel[0] = color
		time.sleep(interval)
		

#---------------------------O2 sensor calibration---------------------------
led[0] = (104, 99, 245)
calMilivolts = AnalogIn(ads, ADS.P0, ADS.P1).voltage * 1000
for cx in range(20):
	calMV = calMV + calMilivolts
cal = abs(calMV / 20)

#---------------------------GPS initialization---------------------------
led[0] = (255, 255, 102)
while True:
      rawNmea = GPS.readline().decode().strip()
      if rawNmea.startswith("$GPRMC") or rawNmea.startswith("$GPGGA"):
            gps = pynmea2.parse(rawNmea)
            latitude = round(gps.latitude, 6)
            longitude = round(gps.longitude, 6)
            if latitude != 0.0 and longitude!= 0.0:
                 blink(led, 3, 0.2, (145, 255, 102))
                 break
            
#---------------------------SCD40 initialization---------------------------
led[0] = (140, 0, 255)
scd40.start_periodic_measurement()

#---------------------------base height of the cansat---------------------------

baseHeight = pvlib.atmosphere.pres2alt(ms8607sensor.pressure * 100)

#---------------------------NRF24L01 initialization---------------------------
led[0] = (20, 41, 227)
THIS_NODE = 0o1
OTHER_NODE = 0o0

radio = RF24(22, 0)
network = RF24Network(radio)

if not radio.begin():
    blink(led, 5, 0.2, (255, 0, 0))
    raise OSError("nRF24L01 hardware isn't responding")

radio.channel = 90
radio.data_rate = RF24_2MBPS
network.begin(THIS_NODE)

#---------------------------parachute larguage process---------------------------
def larguage_process():
      while True:
        time.sleep(0.05)

        GPIO.output(Trig, True)

        time.sleep(0.00001)

        GPIO.output(Trig, False)
        while GPIO.input(Echo)==0:
            debutImpulsion = time.time()

        while GPIO.input(Echo)==1:
            finImpulsion = time.time()

        distance = round((finImpulsion - debutImpulsion) * 340 * 100 / 2, 1)  ## Vitesse du son = 340 m/s
        print(distance)
        if distance < 101:
            os.system("python3 90.py")
            led[0] = (58, 157, 35)
            time.sleep(1)
            break

#---------------------------Main code---------------------------
if __name__ == "__main__":
    while True:
         print(pvlib.atmosphere.pres2alt(ms8607sensor.pressure * 100), baseHeight)
         if pvlib.atmosphere.pres2alt(ms8607sensor.pressure * 100) > baseHeight + 20:
              blink(led, 5, 0.2, (0, 255, 0))
              break
    try:
        while True:
            network.update()
            if pvlib.atmosphere.pres2alt(ms8607sensor.pressure * 100) < baseHeight + 10:
                 if (fall == False):
                      larguage_process()
                      fall = True
                 oldHeight = pvlib.atmosphere.pres2alt(ms8607sensor.pressure * 100)
                 time.sleep(10)
                 newHeight = pvlib.atmosphere.pres2alt(ms8607sensor.pressure * 100)
                 
                 if math.isclose(oldHeight, newHeight, rel_tol=0.1):
                      led[0] = (245, 147, 27)
                      dt = datetime.datetime.now()
                      cam.capture(f'./toSend/{dt.month}-{dt.day}-{dt.hour}-{dt.minute}-{dt.second}.png')
                      bytesImg = open(f'./toSend/{dt.month}-{dt.day}-{dt.hour}-{dt.minute}-{dt.second}.png', "rb").read()
                      bytesArray = [bytesImg[i:i+20] for i in range(0, len(bytesImg), 20)]
                      for b in bytesArray:
                           led[0] = (0, 0, 0)
                           #print(b)
                           ok = network.write(RF24NetworkHeader(OTHER_NODE), b)
                           if ok :
                                led[0] = (0, 50, 0)
                           else:
                                led[0] = (50, 0, 0)
                      break
                                
            led[0] = (0, 0, 0)

            if rawNmea.startswith("$GPRMC") or rawNmea.startswith("$GPGGA"):
                GPSinfos = pynmea2.parse(rawNmea)
                latitude = round(GPSinfos.latitude, 8)
                longitude = round(GPSinfos.longitude, 8)
        
            milivolts = AnalogIn(ads, ADS.P0, ADS.P1).voltage * 1000
            O2result = (milivolts / cal) * 20.9
            if (milivolts + multiplier) < 0.02 and O2result <= 0:
                blink(led, 5, 0.1, (227, 66, 111))
                o2 = 0
            else:
                o2 = round(O2result, 2)
        
            pressure = round(ms8607sensor.pressure, 2)
            temp = round(ms8607sensor.temperature, 2)
            humidity = round(ms8607sensor.relative_humidity, 2)
        
            if scd40.data_ready:
                co2 = scd40.CO2
        
            payload = struct.pack("<Bfffffif", 0x01, latitude, longitude, pressure, temp, humidity, co2, o2)
            ok = network.write(RF24NetworkHeader(OTHER_NODE), payload)
            if ok :
                led[0] = (0, 50, 0)
            else:
                led[0] = (50, 0, 0)
            cam.capture(f'./misc/{datetime.datetime.now().month}-{datetime.datetime.now().day}-{datetime.datetime.now().hour}-{datetime.datetime.now().minute}-{datetime.datetime.now().second} {pvlib.atmosphere.pres2alt(ms8607sensor.pressure * 100)}m.png')
            
        while True:
            led[0] = (0, 0, 0)
            radio.power = True
            if minutes == 60:
                 led[0] = (245, 147, 27)
                 dt = datetime.datetime.now()
                 cam.capture(f'./toSend/{dt.month}-{dt.day}-{dt.hour}-{dt.minute}-{dt.second}.png')
                 bytesImg = open(f'./toSend/{dt.month}-{dt.day}-{dt.hour}-{dt.minute}-{dt.second}.png', "rb").read()
                 bytesArray = [bytesImg[i:i+20] for i in range(0, len(bytesImg), 20)]
                 for b in bytesArray:
                       led[0] = (0, 0, 0)
                       ok = network.write(RF24NetworkHeader(OTHER_NODE), payload)
                       if ok :
                            led[0] = (0, 50, 0)
                       else:
                            led[0] = (50, 0, 0)
            time.sleep(60)
            if rawNmea.startswith("$GPRMC") or rawNmea.startswith("$GPGGA"):
                GPSinfos = pynmea2.parse(rawNmea)
                latitude = round(GPSinfos.latitude, 8)
                longitude = round(GPSinfos.longitude, 8)
        
            milivolts = AnalogIn(ads, ADS.P0, ADS.P1).voltage * 1000
            O2result = (milivolts / cal) * 20.9
            if (milivolts + multiplier) < 0.02 and O2result <= 0:
                blink(led, 5, 0.1, (227, 66, 111))
                o2 = 0
            else:
                o2 = round(O2result, 2)
        
            pressure = round(ms8607sensor.pressure, 2)
            temp = round(ms8607sensor.temperature, 2)
            humidity = round(ms8607sensor.relative_humidity, 2)
        
            if scd40.data_ready:
                co2 = scd40.CO2
        
            payload = struct.pack("<Bfffffif", 0x01, latitude, longitude, pressure, temp, humidity, co2, o2)
            ok = network.write(RF24NetworkHeader(OTHER_NODE), payload)
            if ok :
                led[0] = (0, 50, 0)
            else:
                led[0] = (50, 0, 0)
            cam.capture(f'./misc/{datetime.datetime.now().month}-{datetime.datetime.now().day}-{datetime.datetime.now().hour}-{datetime.datetime.now().minute}-{datetime.datetime.now().second} {pvlib.atmosphere.pres2alt(ms8607sensor.pressure * 100)}m.png')
            radio.power = False
            minutes = minutes + 1

    except InterruptedError or KeyboardInterrupt:
        print("powering down radio and exiting.")
        led[0] = (0, 0, 0)
        radio.power = False