import random
import time
import machine
from simple_pid.PID import PID
from controller.controller import PlatformController
from imu.imu import ImuController
from motor.motor import ServoController
from config.config import Config

class PIDPlatformController(PlatformController):
    """
    Control the antenna motion device of the antenny.
    """

    def __init__(
            self,
            azimuth: ServoController,
            elevation: ServoController,
            imu: ImuController,
            pid_output_limits: tuple = (-20, 20),
            pid_frequency: int = 100,
            p: float = 1.0,
            i: float = 0.0,
            d: float = 0.0,
    ):
        self.azimuth = azimuth
        self.elevation = elevation
        self.imu = imu
        self._motion_started = False
        self.pin_interrupt = True
        self.deadzone = None
        self.timer_id = Config('antenny').get('pid_timer_id')
        print("PID controller using timer hardware id: %d" % (self.timer_id))
        self.pid_loop_timer = machine.Timer(self.timer_id)
        self.elevation.set_position(int((self.elevation.get_max_position() - self.elevation.get_min_position()) / 2))
        self.azimuth.set_position(int((self.azimuth.get_max_position() - self.azimuth.get_min_position()) / 2))
        self.new_elevation = 0
        self.new_azimuth = 0
        self.pid_output_limits = pid_output_limits
        self.pid_frequency = pid_frequency
        self.p = p
        self.i = i
        self.d = d
        self.elevation_pid = None
        self.azimuth_pid = None
        self.init_pid()

    def init_pid(self):
        self.elevation_pid = PID(
            setpoint=self.new_elevation,
            output_limits=self.pid_output_limits,
            Kp=self.p,
            Ki=self.i,
            Kd=self.d
        )
        self.azimuth_pid = PID(
            setpoint=self.new_azimuth,
            output_limits=self.pid_output_limits,
            Kp=self.p,
            Ki=self.i,
            Kd=self.d
        )

    def start(self):
        self.start_pid_loop()

    def stop(self):
        self.stop_pid_loop()

    def set_azimuth(self, azimuth):
        """
        Sets the platform to point at a specified azimuth
        :param azimuth:
        :return:
        """
        if self.deadzone is None:
            print("You must orient the device before setting its coordinates!")
            return
        for dead_zone_min, dead_zone_max in self.deadzone:
            if dead_zone_min < azimuth < dead_zone_max:
                print("That coordinate is out of the servo limit, please realign your platform and re-orient")
                return
        self.new_azimuth = azimuth

    def get_azimuth(self):
        """
        Gets the current azimuth of the platform
        :return:
        """
        return self.imu.get_azimuth()

    def set_elevation(self, elevation):
        """
        Sets the platform to point at a specified elevation
        :param elevation:
        :return:
        """
        elevation = elevation
        self.new_elevation = elevation

    def get_elevation(self):
        """
        Gets the current elevation of the platform
        :return:
        """
        return self.imu.get_elevation()

    def start_pid_loop(self):
        """
        Initializes the PID timer interrupt
        :return:
        """
        self.new_elevation = self.imu.get_elevation()
        self.new_azimuth = self.imu.get_azimuth()
        self.azimuth_pid.setpoint = self.new_azimuth
        self.elevation_pid.setpoint = self.new_elevation
        self.pid_loop_timer.init(period=self.pid_frequency, mode=machine.Timer.PERIODIC, callback=self.__pid_loop)

    def stop_pid_loop(self):
        """
        Stops the PID timer
        :return:
        """
        self.pid_loop_timer.deinit()

    def set_coordinates(self, azimuth, elevation):
        """
        Sets relative coordinates to point at
        :param error:
        :param azimuth:
        :param elevation:
        :return:
        """
        self.set_elevation(elevation)
        self.set_azimuth(azimuth)

    def __pid_loop(self, timer):
        """
        PID ISR
        :return:
        """
        self.elevation_pid.setpoint = self.new_elevation
        self.azimuth_pid.setpoint = self.new_azimuth
        _elevation = self.get_elevation()
        _azimuth = self.get_azimuth()
        el_duty = int(self.elevation_pid(_elevation))
        az_duty = int(self.azimuth_pid(_azimuth)) * -1
        self.elevation.step(el_duty)
        self.azimuth.step(az_duty)
        # print("""
        # azimuth: {}
        # azimuth_duty: {}
        # elevation: {}
        # elevation_duty: {}
        # """.format(_azimuth, az_duty, _elevation, el_duty))

    def auto_calibrate_accelerometer(self):
        """
        Uses the servos to calibrate the accelerometer
        :return:
        """
        old_mode = self.imu.prepare_calibration()
        accel_level = self.imu.get_accelerometer_status()
        prev_accel_level = accel_level
        print("Calibrating accelerometer")
        print("Configuration level: {}".format(accel_level))
        start = time.time()
        while accel_level < 3:
            if time.time() - start > 2:
                self.elevation.set_position(
                    random.randint(
                        self.elevation.get_min_position(),
                        self.elevation.get_max_position()
                    )
                )
                self.azimuth.set_position(
                    random.randint(
                        self.azimuth.get_min_position(),
                        self.azimuth.get_max_position()
                    )
                )
                start = time.time()
            accel_level = self.imu.get_accelerometer_status()
            if accel_level != prev_accel_level:
                print("Configuration level: {}".format(accel_level))
                prev_accel_level = accel_level
        print("Accelerometer calibration done!")
        self.imu.mode(old_mode)
        return self.imu.save_accelerometer_calibration()

    def auto_calibrate_magnetometer(self):
        """
        Uses the servos to calibrate the magnetometer
        :return:
        """
        old_mode = self.imu.prepare_calibration()
        magnet_level = self.imu.get_magnetometer_status()
        prev_magnet_level = magnet_level
        print("Calibrating magnetometer")
        print("Configuration level: {}".format(magnet_level))
        start = time.time()
        count = 0
        count_2 = 0
        self.elevation.set_position(self.elevation.get_min_position())
        while magnet_level < 3:
            if time.time() - start > 2:
                self.azimuth.set_position(self.azimuth.get_min_position() + count)
                count += int((self.azimuth.get_max_position() - self.azimuth.get_min_position()) / 8)
                if count + self.azimuth.get_min_position() > self.azimuth.get_max_position():
                    count_2 += int((self.elevation.get_max_position() - self.elevation.get_min_position()) / 8)
                    if count_2 + self.elevation.get_min_position() > self.elevation.get_max_position():
                        count_2 = 0
                    self.elevation.set_position(self.elevation.get_min_position() + count_2)
                    count = 0
                start = time.time()
            magnet_level = self.imu.get_magnetometer_status()
            if magnet_level != prev_magnet_level:
                print("Configuration level: {}".format(magnet_level))
                prev_magnet_level = magnet_level
        print("Magnetometer calibration done!")
        self.imu.mode(old_mode)
        return self.imu.save_magnetometer_calibration()

    def auto_calibrate_gyroscope(self):
        """
        Uses the servos to calibrate the gyroscope
        :return:
        """
        old_mode = self.imu.prepare_calibration()
        gyro_level = self.imu.get_gyro_status()
        prev_gyro_level = gyro_level
        print("Calibrating gyroscope")
        print("Configuration level: {}".format(gyro_level))
        while gyro_level < 3:
            gyro_level = self.imu.get_gyro_status()
            if gyro_level != prev_gyro_level:
                print("Configuration level: {}".format(gyro_level))
                prev_gyro_level = gyro_level
        print("Gyr calibration done!")
        self.imu.mode(old_mode)
        return self.imu.save_gyroscope_calibration()

    @staticmethod
    def get_delta(current, prev):
        """
        Gets the difference in the angle
        :param current:
        :param prev:
        :return:
        """
        d = abs(current - prev)
        if d > 180:
            d = 360 - d
        return d

    def auto_calibrate_elevation_servo(self, us=100, d=.5, t=.1):
        """
        Uses the IMU to calibrate the elevation servo
        :param us:
        :param d:
        :return:
        """
        moving = False
        first_move = False
        self.elevation.set_min_position(0)
        self.elevation.set_max_position(4095)
        self.elevation.set_position(int((self.azimuth.get_max_position() - self.azimuth.get_min_position()) / 2))
        time.sleep(1)
        prev_elevation = self.imu.get_elevation()
        for i in range(self.elevation.get_min_position(), self.elevation.get_max_position(), us):
            self.elevation.set_position(i)
            time.sleep(t)
            current = self.imu.get_elevation()
            delta = self.get_delta(current, prev_elevation)
            print("{}: {}".format(i, delta))
            if (delta > d) and not first_move:
                first_move = True
                print("First movement detected at {}".format(i))
                print("Waiting again")
                print("Previous: {}".format(prev_elevation))
                print("Current: {}".format(current))
                print("Delta: {}".format(delta))
            elif (delta > d) and first_move and not moving:
                moving = True
                print("Movement detected at {}".format(i))
                print("Previous: {}".format(prev_elevation))
                print("Current: {}".format(current))
                print("Delta: {}".format(delta))
                self.elevation.min_us = i + 100
            elif (delta < d) and moving:
                self.elevation.set_position(i+100)
                try_again_delta = self.get_delta(self.imu.get_elevation(), current)
                if try_again_delta > d:
                    continue
                print("No movement detected at {}".format(i))
                print("Previous: {}".format(prev_elevation))
                print("Current: {}".format(current))
                print("Delta: {}".format(delta))
                self.elevation.max_us = i - 100
                return
            prev_elevation = current

    def auto_calibrate_azimuth_servo(self, us=100, d=.5, t=.1):
        """
        Uses the IMU to calibrate the azimuth servo
        :param us:
        :param d:
        :return:
        """
        moving = False
        first_move = False
        self.azimuth.set_min_position(0)
        self.azimuth.set_max_position(4095)
        self.elevation.set_position(int((self.azimuth.get_max_position() - self.azimuth.get_min_position()) / 2))
        self.azimuth.set_position(int((self.azimuth.get_max_position() - self.azimuth.get_min_position()) / 2))
        time.sleep(1)
        prev_azimuth = self.imu.get_azimuth()

        for i in range(self.azimuth.get_min_position(), self.azimuth.get_max_position(), us):
            self.azimuth.set_position(i)
            time.sleep(t)
            current = self.imu.get_azimuth()
            delta = self.get_delta(current, prev_azimuth)
            print("{}: {}".format(i, delta))
            if (delta > d) and not first_move:
                first_move = True
                print("First movement detected at {}".format(i))
                print("Waiting again")
                print("Previous: {}".format(prev_azimuth))
                print("Current: {}".format(current))
                print("Delta: {}".format(delta))
            elif (delta > d) and first_move and not moving:
                moving = True
                print("Movement detected at {}".format(i))
                print("Previous: {}".format(prev_azimuth))
                print("Current: {}".format(current))
                print("Delta: {}".format(delta))
                self.azimuth.min_us = i + 100
            elif (delta < d) and moving:
                self.azimuth.set_position(i+100)
                try_again_delta = self.get_delta(self.imu.get_azimuth(), current)
                if try_again_delta > d:
                    continue
                print("No movement detected at {}".format(i))
                print("Previous: {}".format(prev_azimuth))
                print("Current: {}".format(current))
                print("Delta: {}".format(delta))
                self.azimuth.max_us = i - 100
                return
            prev_azimuth = current

    def orient(self):
        """
        Finds the current orientation. Saves and reports the servo azimuth deadzone.
        :return:
        """
        self.azimuth.set_position(self.azimuth.get_min_position())
        time.sleep(1)
        min_azimuth = self.imu.get_azimuth()
        self.azimuth.set_position(self.azimuth.get_max_position())
        time.sleep(1)
        max_azimuth = self.imu.get_azimuth()
        if min_azimuth > max_azimuth:
            self.deadzone = [(min_azimuth, 360), (0, max_azimuth)]
        else:
            self.deadzone = [(min_azimuth, max_azimuth)]
        return self.deadzone
