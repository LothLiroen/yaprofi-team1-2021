#!/usr/bin/env python
import rospy
from std_msgs.msg import Empty
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist, Point, Pose
from tello_driver.msg import TelloStatus
import threading
import sys
import tf.transformations as tftr
from tello_driver.msg import CartesianTrajectory
from numpy import *

lock = threading.Lock()

# DEFINES

FILE_NAME = '/home/root/catkin_ws/src/tello_driver/src/test_log.txt'

Alpha = 0

FRAC_PART = 4

EPSILON = 0.089
ERROR_ANGLE = 0.5
V_MAX   = 0.5 # m/s
W_MAX   = 0.5 # rad/s

H = 2.0 # m

class Tello:

    def __init__(self):
        # Creates a node with name 'tello_controller' and make sure it is a
        # unique node
        rospy.init_node('tello_controller', anonymous=True)

        self.takeoff_publisher = rospy.Publisher('/tello/takeoff', Empty, queue_size=1)
        self.land_publisher = rospy.Publisher('/tello/land', Empty, queue_size=1)

        self.velocity_publisher = rospy.Publisher('/tello/cmd_vel', Twist, queue_size=5)

        self.status_subscriber = rospy.Subscriber('/tello/status', TelloStatus, self.get_status)

        self.trajectory_sub = rospy.Subscriber("/tello/trajectory", CartesianTrajectory, self.trajectory_callback)
        self.trajectory = []

        self.status = None

        self.odom_subscriber = rospy.Subscriber('/tello/odom', Odometry, self.update_odom)

        self.x   = None
        self.y   = None
        self.z   = None
        self.q   = None
        self.rpy = None
        self.theta = None
        self.theta_start = None

        self.time_start = -1.0
        self.start = Pose()

        self.file = open(FILE_NAME, 'w')

        self.rate = rospy.Rate(60)

        self.state = 0

    def get_status(self, data):
        # Dron status callback function
        lock.acquire()

        self.status = data

        lock.release()

    def trajectory_callback(self, msg): ##
        """
        Trajectory for Robotino.
        Gets trajectory from robotino_trajectory_generator_node and saves to self variable.
        """
        lock.acquire()
        if self.trajectory == []:
            for pose in msg.poses:
                self.trajectory.append(pose)
            print( len(self.trajectory) )
        lock.release()

    def exists_trajectory(self): ##
        if self.trajectory is not None:
            return True
        else:
            return False

    def set_start(self):
        self.time_start = rospy.get_time()

        self.start.position.x = self.x
        self.start.position.y = self.y
        self.start.position.z = self.z

        self.start.orientation = self.q
        self.theta_start = tftr.euler_from_quaternion((self.q.x, self.q.y, self.q.z, self.q.w))[2]

    def update_odom(self, data):
        # Odometry callback function
        lock.acquire()

        self.x = round(data.pose.pose.position.x, FRAC_PART)
        self.y = round(data.pose.pose.position.y, FRAC_PART)
        self.z = round(data.pose.pose.position.z, FRAC_PART)

        self.q = data.pose.pose.orientation
        self.rpy = tftr.euler_from_quaternion((self.q.x, self.q.y, self.q.z, self.q.w))  # roll pitch yaw
        self.theta = self.rpy[2]

        lock.release()

        # Log file

        self.file.write( 'Time from start : {0} X : {1} Y: {2} Z: {3} \n '.format(round((rospy.get_time()-self.time_start), FRAC_PART), self.x - self.start.position.x, self.y - self.start.position.y, self.z - self.start.position.z) )

    def linear_distance(self, goal_point):
        return sqrt((goal_point.x - self.x)**2 +
                    (goal_point.y - self.y)**2 +
                    (goal_point.z - self.z)**2 )

    def angular_distance(self, goal_angle):
        # in oXY
        return sqrt( (goal_angle - self.theta) ** 2)

    def steering_angle(self, goal_pose):
        return atan2(goal_pose.y - self.pose.y, goal_pose.x - self.pose.x)

    def angular_vel(self, goal_pose, constant=30):
        return constant * (self.steering_angle(goal_pose) - self.pose.theta)

    def gp(self, msg):
        for i in range(len(self.trajectory.poses)):
            goal_pose = self.trajectory.poses[i]
        return goal_pose

    def saturation(self, vel_raw):
        # v_x
        if vel_raw.linear.x > V_MAX:
            vel_raw.linear.x = V_MAX
        elif vel_raw.linear.x < -V_MAX:
            vel_raw.linear.x = -V_MAX
        # v_y
        if vel_raw.linear.y > V_MAX:
            vel_raw.linear.y = V_MAX
        elif vel_raw.linear.y < -V_MAX:
            vel_raw.linear.y = -V_MAX
        # v_z
        if vel_raw.linear.z > V_MAX:
            vel_raw.linear.z = V_MAX
        elif vel_raw.linear.z < -V_MAX:
            vel_raw.linear.z = -V_MAX
        # w_x
        if vel_raw.angular.x > W_MAX:
            vel_raw.angular.x = W_MAX
        elif vel_raw.angular.x < -W_MAX:
            vel_raw.angular.x = -W_MAX
        # w_y
        if vel_raw.angular.y > W_MAX:
            vel_raw.angular.y = W_MAX
        elif vel_raw.angular.y < -W_MAX:
            vel_raw.angular.y = -W_MAX
        # w_z
        if vel_raw.angular.z > W_MAX:
            vel_raw.angular.z = W_MAX
        elif vel_raw.angular.z < -W_MAX:
            vel_raw.angular.z = -W_MAX

        return vel_raw

    def take_off(self):
        msg = Empty()
        self.takeoff_publisher.publish(msg)

    def land(self):
        msg = Empty()
        self.land_publisher.publish(msg)
        self.file.close()

    def set_velocity(self, v_x=0, v_y=0, v_z=0, w_x=0, w_y=0, w_z=0):

        vel_msg = Twist()

        psi = - (self.theta - self.theta_start)

        vel_msg.linear.x = v_x * cos(psi) - v_y * sin(psi)
        vel_msg.linear.y = v_x * sin(psi) + v_y * cos(psi)
        vel_msg.linear.z = v_z

        vel_msg.angular.x = w_x
        vel_msg.angular.y = w_y
        vel_msg.angular.z = w_z

        self.velocity_publisher.publish( self.saturation(vel_msg) )

    def rotation(self, angle):
        k_p = 2.15

        goal_angle = angle + self.theta

        err = self.angular_distance(goal_angle)
        while abs(err) > ERROR_ANGLE:
            w_z = k_p * (goal_angle - self.theta)

            self.set_velocity(w_z = w_z)

            err = self.angular_distance(goal_angle)
            print 'Err: {0}, w_z : {1} x : {2} y : {3}'.format(err, w_z, self.x, self.y)

        self.set_velocity()


    def go_to_point(self, goal_point):
        k_p = 1.25

        err = self.linear_distance(goal_point)

        try:
            yaw = self.trajectory[self.state].theta # atan2(self.trajectory[self.state+1].y - self.trajectory[self.state].y, self.trajectory[self.state+1].x - self.trajectory[self.state].x)
        except:
            pass
        while abs(err) > EPSILON:
            v_x = k_p * (goal_point.x - self.x)
            v_y = k_p * (goal_point.y - self.y)
            v_z = k_p * (goal_point.z - self.z)

            e_theta = yaw - (self.theta - self.theta_start) 

            w_z = k_p * e_theta

            self.set_velocity(v_x, v_y, v_z, 0, 0, w_z)


            self.rate.sleep()

            err = self.linear_distance(goal_point)
            # print 'Err: {0}, vx : {1}, vy : {2} x : {3} y : {4}'.format(err, v_x, v_y, self.x, self.y)

        # self.set_velocity()

    def transform_point(self, point_to_transform):
        # x_world -> x_robot
        # y_world -> -y_robot
        # z_world -> -z_robot

        result_point = Point()

        result_point.x =   point_to_transform.x + self.start.position.x
        result_point.y = - point_to_transform.y + self.start.position.y
        result_point.z = - point_to_transform.z

        return result_point

    def do_eight(self):
        while(self.state < len(self.trajectory)):
            a = Point(self.trajectory[self.state].x, self.trajectory[self.state].y, H)
            a = self.transform_point(a)
            self.go_to_point(a)

            print(self.state)
            self.state += 1

if __name__ == '__main__':
    try:
        drone = Tello()
        # f = open('/home/root/catkin_ws/src/tello_driver/src/test.txt', 'w')
        # f.write('1 \n')
        # f.write('2\n')
        # f.close()
        rospy.Rate(1).sleep() # Setiing up a subscriber may take a while ...

        print 'Taking off ...'

        drone.take_off()
        rospy.sleep(7)
        drone.set_start()
        print 'Start position : [{0}, {1}, {2}]'.format(drone.start.position.x, drone.start.position.y, drone.start.position.z)
        rospy.sleep(3)

        drone.do_eight()

        print 'Landing ...'
        drone.land()
        rospy.sleep(1)

        print('killing controller ...') 
    #rospy.spin()
    except rospy.ROSInterruptException:
        pass