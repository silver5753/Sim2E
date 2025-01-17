"""
Written by Mr. Guy Tordjman 
@ The Neuro-Biomorphoc Engineering Lab (NBEL-lab.com)
@ The Open University of Israel
@ Dec 07 2021

Physical simulation is based the MuJoCo open source simulator (http://www.mujoco.org)

This class solves the IK problem and creates a list of states.
Each state is a dictionary of joint torques

"""

import numpy as np
from cv2 import sqrt
from sympy import rot_axis1, rot_axis2
from cmath import acos

from project.simulation.state_machine import States


class SimpleStateMachine:
    def __init__(self, robot, scene, control, orientation=0, look_at_target=True) -> None:
        self.robot = robot
        self.scene = scene
        self.control = control
        self.simulation = self.scene.simulation
        self.model = self.scene.model
        self.orientation = orientation
        # targets are [x, y, z] coordinates
        self.targets = [self.scene.get_target_pos_euler()[0]]
        #th to position ee infront of target
        self.y_th = 0.5
        self.thetas = None
        self.curr_state_target = self.robot.ee_home
        self.curr_final_target = self.targets[0]
        orientations = [np.array([[0, 0, 1],
                                  [1, 0, 0],
                                  [0, 1, 0]], dtype=np.float64),
                        np.array([[0, 0, 1],
                                  [0, 1, 0],
                                  [-1,0, 0]], dtype=np.float64)]
        self.target_orientation = orientations[orientation]
        self.curr_state_configuration = []
        self.steps_positions = []
        self.steps_thetas = []
        self.reached_th = 0.06
        self.curr_state = States.INIT
        self.prev_state = States.INIT
        self.targets_counter = 0
        self.steps_counter = 0
        self.num_steps = 100
        self.distance = 0
        self.is_return = True
        self.get_random_targets()
        self.start_pos = robot.ee_home if orientation==0 else robot.ee_face_down
        self.start_config = robot.home if orientation==0 else robot.face_down
        self.start_orientation = self.target_orientation

        self.look_at_target = look_at_target
        self.look_at_y_theta = 0
        self.look_at_z_theta = 0
        self.look_at_config = self.start_config
        # print(self.targets)

    def get_random_targets(self):
        y = self.curr_final_target[1]
        z = self.curr_final_target[2]
        num = 100
        x = list(np.random.randint(low = -35,high=35,size=50))
        rand_y = list(np.random.randint(low = 25,high=60,size=50))
        if self.orientation==0:
            for i in x:
                if abs(i) >= 15:
                    self.targets.append([i/100,y,z])
        else:
            for _x, _y in zip(x, rand_y):
                self.targets.append([_x/100,_y/num,z])

    def next_state(self):

        # next state depending on current state and the distance between the EE to the current state target
        # self.distance = np.linalg.norm(self.robot.get_ee_position() - self.curr_state_target )
        self.distance = np.linalg.norm(self.robot.get_joints_pos() - self.control.theta_d )

        # init state to get data for the current target
        if self.curr_state == States.INIT:
            self.steps_positions = []
            self.steps_thetas = []
            #set final target
            self.curr_final_target = self.targets[self.targets_counter]
            #set state target and configuration
            self.curr_state_target = self.start_pos
            self.curr_state_configuration = self.start_config
            #next state
            self.curr_state = States.HOME
            self.steps_counter = 0
            #next time that the INIT state is reached move on to the next target
            self.targets_counter += 1
            if self.targets_counter == len(self.targets):
                print("Simulation is out of targets")
                exit(1)

        # primary condition to move to the next step is the distance to the current state target
        elif self.distance < self.reached_th:
            if self.curr_state == States.HOME:
                self.simulation.data.set_mocap_pos("target",  self.curr_final_target)
                if not self.look_at_target:
                    # create the next states, positions
                    self.steps_positions = [] #empty list
                    curr_ee_pos = self.robot.get_ee_position()
                    diff = self.curr_final_target - curr_ee_pos
                    for i in range(self.num_steps):
                        self.steps_positions.append((curr_ee_pos+((i+1)/self.num_steps)*diff))
                    # set the next state as the steps
                    self.curr_state = States.STEPS
                    self.set_step()
                else:
                    self.calculate_look_at_target_angles()
                    curr_htm = self.control.FK(self.robot.get_joints_pos())
                    curr_rot = curr_htm[:3, :3]
                    look_at_rot = np.dot(rot_axis2(self.look_at_y_theta), rot_axis1(self.look_at_z_theta))
                    curr_rot = np.dot(look_at_rot, curr_rot)
                    curr_htm[:3, :3] = curr_rot
                    self.target_orientation = np.array(curr_rot, dtype=np.float64)
                    self.curr_state_target = self.start_pos
                    self.look_at_config = self.control.IK(curr_htm)
                    self.curr_state = States.LOOK

            elif self.curr_state == States.LOOK:

                # create the next states, positions
                self.steps_positions = [] #empty list
                curr_ee_pos = self.robot.get_ee_position()
                diff = self.curr_final_target - curr_ee_pos
                for i in range(self.num_steps):
                    self.steps_positions.append((curr_ee_pos+((i+1)/self.num_steps)*diff))
                # set the next state as the steps
                self.curr_state = States.STEPS
                self.set_step()

            elif self.curr_state == States.STEPS+self.steps_counter:
                self.steps_counter += 1
                if self.steps_counter >= self.num_steps:
                    if self.is_return:
                        self.curr_state = States.RETURN
                    else:
                        self.curr_state = States.INIT
                    self.steps_counter = 0
                    self.is_return = not self.is_return
                else:
                    self.set_step()

            elif self.curr_state == States.RETURN:
                self.steps_positions = [] #empty list
                curr_ee_pos = self.robot.get_ee_position()
                diff = self.start_pos - curr_ee_pos
                for i in range(self.num_steps):
                    self.steps_positions.append((curr_ee_pos+((i+1)/self.num_steps)*diff))
                # set the next state as the steps
                self.curr_state = States.STEPS
                self.set_step()



    def output(self):
        #output is dependant of the current state
        if self.curr_state != self.prev_state:
            if self.curr_state == States.HOME or self.curr_state == States.INIT:
                self.control.phase = 0
                self.control.theta_d = self.start_config

            elif  self.curr_state == States.LOOK:
                self.control.phase = 0
                self.control.theta_d = self.look_at_config

            else:
                self.control.phase = 1
                thetas = self.control.IK(self.curr_state_configuration)
                self.steps_thetas.append(thetas)
                self.control.theta_d = thetas

            if self.steps_counter >= int(self.num_steps*0.93):
                self.control.phase = 2

            self.prev_state = self.curr_state

    def set_step(self):
        self.curr_state_target = self.steps_positions[self.steps_counter]
        self.curr_state_configuration = np.r_[np.c_[self.target_orientation, self.curr_state_target], [[0,0,0,1]]]
        self.curr_state = States.STEPS + self.steps_counter

    def step_back(self):
        self.curr_state_target = self.steps_positions[self.steps_counter]
        self.curr_state = States.RETURN + self.steps_counter

    def calculate_look_at_target_angles(self):
        # align the x axis with a vector facing the target --> No X rotation
        # rotation are limited to the y and z axis only

        if self.look_at_target is False:
            self.look_at_y_theta = 0
            self.look_at_z_theta = 0
            return
        # step 1 get direction vector of ee to target in world space
        thetas = self.robot.get_joints_pos()
        T_se = self.control.FK(thetas)
        R_se = T_se[:3, :3]
        # p_sb = np.append(self.curr_final_target, [1])
        p_sb = self.curr_final_target
        p_se = self.robot.get_ee_position()
        p_s_eb = p_se - p_sb

        p_eb = np.dot(R_se, p_s_eb)


        x = p_eb[0]
        y = p_eb[1]
        z = p_eb[2]

        # step 2 get angle of rotation about the z
        mag = sqrt(x**2 + y**2)[0]
        if y >= 0:
            self.look_at_z_theta = acos(x/mag)
        else:
            self.look_at_z_theta = -acos(x/mag)

        #step 3 get angle of rotation about the y
        mag = sqrt(x**2 +z**2)[0]
        if z >= 0:
            self.look_at_y_theta = acos(x/mag)
        else:
            self.look_at_y_theta =  -acos(x/mag)



    def eval(self):
        self.next_state()
        self.output()