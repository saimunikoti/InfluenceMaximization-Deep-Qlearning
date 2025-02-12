import numpy as np
import random 
from collections import namedtuple, deque 
import dgl
##Importing the model (function approximator for Q-table)
from src.models.models import GraphQNetwork
from src.data import config as cnf
import torch
import torch.optim as optim

BUFFER_SIZE = 5000     # replay buffer size
BATCH_SIZE = 64    # minibatch size
GAMMA = 0.95          # discount factor
TAU = 1e-3             # for soft update of target parameters
LR = 0.0008              # learning rate
UPDATE_EVERY = 1       # how often to update the network
TARGET_UPDATE = 8

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

class Agent():
    """Interacts with and learns form environment."""
    
    def __init__(self, glist, in_feats, hid_feats, hid_mlp, candnodelist, seed, tuningweight, trainmodel_flag=0):

        """Initialize an Agent object.

        Params
        =======
            state_size (int): dimension of each state
            action_size (int): dimension of each action
            seed (int): random seed
        """
        self.graphlist = [dgl.from_networkx(glist[ind], node_attrs=['feature']).to(device) for ind in range(len(glist))]
        self.seed = random.seed(seed)
        self.candidatenodelist = candnodelist

        # objective weights
        self.alpha = tuningweight

        #Q- Network local for obj 1
        self.qnetwork_local1 = GraphQNetwork(in_feats= in_feats, hid_feats=hid_feats, hid_mlp=hid_mlp).to(device)
        # Q- Network local for obj 2
        self.qnetwork_local2 = GraphQNetwork(in_feats= in_feats, hid_feats=hid_feats, hid_mlp=hid_mlp).to(device)
        # Q- Network target for obj 1
        self.qnetwork_target1 = GraphQNetwork(in_feats= in_feats, hid_feats=hid_feats, hid_mlp=hid_mlp).to(device)
        # Q- Network target for obj 2
        self.qnetwork_target2 = GraphQNetwork(in_feats= in_feats, hid_feats=hid_feats, hid_mlp=hid_mlp).to(device)

        # LOAD PRETRAINED MODEL WEIghts

        if trainmodel_flag == 1:
            checkpointpath1 = cnf.modelpath + "\checkpoint_AIM_wtpdreward1.pth"
            checkpointpath2 = cnf.modelpath + "\checkpoint_AIM_wtpdreward2.pth"
            self.qnetwork_local1.load_state_dict(torch.load(checkpointpath1))
            self.qnetwork_target1.load_state_dict(torch.load(checkpointpath1))
            self.qnetwork_local2.load_state_dict(torch.load(checkpointpath2))
            self.qnetwork_target2.load_state_dict(torch.load(checkpointpath2))
            print("=== trained model successfully loaded===")

        # optimizer for q network local 1
        self.optimizer1 = optim.Adam(self.qnetwork_local1.parameters(), lr=LR)
        # optimizer for q network local 1
        self.optimizer2 = optim.Adam(self.qnetwork_local2.parameters(), lr=LR)

        # Replay memory 
        self.memory = ReplayBuffer(BUFFER_SIZE,BATCH_SIZE, seed)

        # Initialize time step (for updating every UPDATE_EVERY steps)
        self.t_step = 0

        # training loss for Q network local 1
        self.trainloss1 = []
        # training loss for Q network local 2
        self.trainloss2 = []

    def step(self, state, action, reward, next_step, done):

        # Save experience in replay memory
        self.memory.add(state, action, reward, next_step, done)

        # Learn every UPDATE_EVERY time steps.
        self.t_step = (self.t_step+1)% UPDATE_EVERY

        if self.t_step == 0:
            # If enough samples are available in memory, get random subset and learn

            if len(self.memory) > (BATCH_SIZE*5):
                experience = self.memory.sample()
                self.learn(experience, GAMMA)

    def train(self, state, action, reward, next_step, done, gindex, reward1, reward2):

        # Save experience in replay memory
        self.memory.add(state, action, reward, next_step, done, gindex, reward1, reward2)
        # print("state, action, reward, next_state", state, action, reward, next_step)
        # print("state, action, reward, next_state", state, action, reward, next_step)

        # train every UPDATE_EVERY time steps.
        # self.t_step = (self.t_step+1) % UPDATE_EVERY

        # if self.t_step == 0:
        experience = self.memory.sample()
        self.learn_morl(experience, GAMMA)

    def get_filledbuffer(self):
        experience = self.memory.sample(batch_size=BUFFER_SIZE)
        return experience

    def get_filledbuffer_wopadding(self):
        experience = self.memory.get_memory()
        return experience

    def get_newmaxreward(self, avg_reward):
        return self.memory.update_avgreward(avg_reward)

    def load_filledbuffer(self, filledbuffer):

        statelist = [list(element) for element in filledbuffer[0].cpu().data.numpy()]
        rewardlist = [element[0] for element in filledbuffer[2].cpu().data.numpy()]
        rewardlist1 = [element[0] for element in filledbuffer[6].cpu().data.numpy()]
        rewardlist2 = [element[0] for element in filledbuffer[7].cpu().data.numpy()]
        next_statelist = [list(element) for element in filledbuffer[3].cpu().data.numpy()]
        donelist = [element[0] for element in filledbuffer[4].cpu().data.numpy()]
        gindexlist = [element[0] for element in filledbuffer[5].cpu().data.numpy()]
        exp = (statelist, filledbuffer[1], rewardlist, next_statelist, donelist, gindexlist, rewardlist1,rewardlist2)

        for state, action, reward, next_step, done, gindex, reward1, reward2 in zip(exp[0], exp[1], exp[2], exp[3], exp[4], exp[5], exp[6], exp[7]):
            self.memory.add(state, action, reward, next_step, done, gindex, reward1, reward2)

    def save_buffer(self, state, action, reward, next_step, done, gindex, reward1, reward2):
        # Save experience in replay memory
        self.memory.add(state, action, reward, next_step, done, gindex, reward1,reward2)

    def act(self, state, candnodelist, gindex, eps = 0):

        """Returns action for given state as per current policy

        Params
        =======
            state (array_like): current state
            eps (float): epsilon, for epsilon-greedy action selection

        """

        # state = torch.from_numpy(state).float().unsqueeze(0).to(device)
        # state = torch.tensor(state).to(device)
        state = torch.tensor(state).to(device)
        candnodelist = torch.tensor(candnodelist).to(device)

        action_values = []

        self.qnetwork_local.eval()
        train_nfeat = self.graphlist[gindex].ndata['feature']
        train_nfeat = torch.tensor(train_nfeat).to(device)

        with torch.no_grad():
            for action in candnodelist:
                action_values.append(self.qnetwork_local(self.graphlist[gindex], train_nfeat, state, action).cpu().data.numpy())

        self.qnetwork_local.train()

        #Epsilon -greedy action selction
        if random.random() > eps:
            action_index = np.argmax(action_values)
        else:
            action_index = random.choice(np.arange(len(candnodelist)))

        return candnodelist[action_index]

    def act_morl(self, state, candnodelist, gindex, eps = 0):

        """Returns action for given state as per current policies

        Params
        =======
            state (array_like): current state
            eps (float): epsilon, for epsilon-greedy action selection

        """

        # state = torch.from_numpy(state).float().unsqueeze(0).to(device)
        # state = torch.tensor(state).to(device)

        state = torch.tensor(state).to(device)
        candnodelist = torch.tensor(candnodelist).to(device)

        action_values = []

        self.qnetwork_local1.eval()
        self.qnetwork_local2.eval()

        train_nfeat = self.graphlist[gindex].ndata['feature']
        train_nfeat = torch.tensor(train_nfeat).to(device)

        with torch.no_grad():
            for action in candnodelist:
                action_values1 = self.qnetwork_local1(self.graphlist[gindex], train_nfeat, state, action).cpu().data.numpy()
                action_values2 = self.qnetwork_local2(self.graphlist[gindex], train_nfeat, state, action).cpu().data.numpy()
                scalrizedQ = self.alpha*action_values1 + (1 - self.alpha)*action_values2
                action_values.append(scalrizedQ)

        self.qnetwork_local1.train()
        self.qnetwork_local2.train()

        #Epsilon -greedy action selction
        if random.random() > eps:
            action_index = np.argmax(action_values)
        else:
            action_index = random.choice(np.arange(len(candnodelist)))

        return candnodelist[action_index]

    def learn(self, experiences, gamma):
        """Update value parameters using given batch of experience tuples.

        Params
        =======

            experiences (Tuple[torch.Variable]): tuple of (s, a, r, s', done) tuples

            gamma (float): discount factor
        """

        states, actions, rewards, next_states, dones, gindexs, rewards1, rewards2 = experiences
        # print("states, actions, rewards, next_states", states.shape, actions.shape, rewards.shape, next_states.shape)

        ## TODO: compute and minimize the loss

        criterion = torch.nn.MSELoss()
        # Local model is one which we need to train so it's in training mode
        self.qnetwork_local.train()
        # Target model is one with which we need to get our target so it's in evaluation mode
        # So that when we do a forward pass with target model it does not calculate gradient.
        # We will update target model weights with soft_update function
        self.qnetwork_target.eval()

        # predicted_targets = []
        # #shape of output from the model (batch_size,action_dim) = (64,4)
        # train_nfeat = self.graphlist[gindex].ndata['feature']

        for count, (count_state, count_action, gindex) in enumerate(zip(states, actions, gindexs)):

            ## predicted_targets.append(self.qnetwork_local(self.graphlist[0], train_nfeat, count_state, count_action).item())
            gindex = int(gindex.item())
            temp_pred = self.qnetwork_local(self.graphlist[gindex], self.graphlist[gindex].ndata['feature'], count_state, count_action)

            if count == 0:
                predicted_targets = temp_pred.clone()
            else:
                predicted_targets = torch.cat([predicted_targets, temp_pred], dim=0)

        # predicted_targets = self.qnetwork_local(self.graphlist[0], train_nfeat, states[0], actions[0])

        # print("predicted_targets raw", self.qnetwork_local(states).shape)
        # print("predicted_targets processed", predicted_targets.shape)

        self.qnetwork_local.eval()

        with torch.no_grad():
            labels_next = []
            for counts, (count_state, gindex) in enumerate(zip(next_states, gindexs)):
                gindex = int(gindex.item())
                candnodes = self.candidatenodelist[gindex].copy()
                candnodes = [ele for ele in candnodes if ele not in count_state]
                candnodes = torch.tensor(candnodes).to(device)

                # temp_label = []
                for counta, count_action in enumerate(candnodes):
                    # temp_label.append(self.qnetwork_target(self.graphlist[0], train_nfeat, count_state, count_action).item())
                    if counta == 0:
                        actions_qlocal = self.qnetwork_local(self.graphlist[gindex], self.graphlist[gindex].ndata['feature'], count_state, count_action)
                    else:
                        actions_qlocal = torch.cat([actions_qlocal, self.qnetwork_local(self.graphlist[gindex], self.graphlist[gindex].ndata['feature'], count_state, count_action)], dim=0)

                # labels_next.append(max(temp_label))
                actions_qlocal = torch.argmax(actions_qlocal)

                temp_label = self.qnetwork_target(self.graphlist[gindex], self.graphlist[gindex].ndata['feature'], count_state, actions_qlocal)
                # temp_label = torch.reshape(torch.max(temp_label), (1,1))

                if counts == 0:
                    labels_next = temp_label
                else:
                    labels_next = torch.cat([labels_next, temp_label], dim=0)
                try:
                    del temp_label, actions_qlocal
                except:
                    pass

        self.qnetwork_local.train()
        # .detach() ->  Returns a new Tensor, detached from the current graph.
        # labels = torch.tensor([rewards[ind] + (gamma*labels_next[ind]*(1-dones[ind])) for ind in range(int(states.shape[0])) ])
        # labels = torch.tensor([rewards[ind] + (gamma*labels_next[ind]*(1-dones[ind])) for ind in range(int(states.shape[0])) ])
        labels = rewards + torch.mul( (torch.mul(labels_next, gamma)),(1-dones))
        # predicted_targets = torch.tensor(predicted_targets)

        loss = criterion(predicted_targets, labels).to(device)
        self.trainloss.append(loss.item())

        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()

        # ------------------- update target network ------------------- #
        self.soft_update(self.qnetwork_local,self.qnetwork_target,TAU)

    def learn_morl(self, experiences, gamma):
        """Update value parameters using given batch of experience tuples.

        Params
        =======

            experiences (Tuple[torch.Variable]): tuple of (s, a, r, s', done) tuples

            gamma (float): discount factor
        """

        states, actions, rewards, next_states, dones, gindexs, rewards1, rewards2 = experiences
        # print("states, actions, rewards, next_states", states.shape, actions.shape, rewards.shape, next_states.shape)

        ## TODO: compute and minimize the loss

        criterion = torch.nn.MSELoss()
        # Local model is one which we need to train so it's in training mode
        self.qnetwork_local1.train()
        self.qnetwork_local2.train()
        # Target model is one with which we need to get our target so it's in evaluation mode
        # So that when we do a forward pass with target model it does not calculate gradient.
        # We will update target model weights with soft_update function
        self.qnetwork_target1.eval()
        self.qnetwork_target2.eval()

        # predicted_targets = []
        # #shape of output from the model (batch_size,action_dim) = (64,4)
        # train_nfeat = self.graphlist[gindex].ndata['feature']
        # predicted targets frrom current Q networks local
        for count, (count_state, count_action, gindex) in enumerate(zip(states, actions, gindexs)):

            ## predicted_targets.append(self.qnetwork_local(self.graphlist[0], train_nfeat, count_state, count_action).item())
            gindex = int(gindex.item())
            temp_pred1 = self.qnetwork_local1(self.graphlist[gindex], self.graphlist[gindex].ndata['feature'], count_state, count_action)
            temp_pred2 = self.qnetwork_local2(self.graphlist[gindex], self.graphlist[gindex].ndata['feature'], count_state, count_action)

            if count == 0:
                predicted_targets1 = temp_pred1.clone()
                predicted_targets2 = temp_pred2.clone()
            else:
                predicted_targets1 = torch.cat([predicted_targets1, temp_pred1], dim=0)
                predicted_targets2 = torch.cat([predicted_targets2, temp_pred2], dim=0)

        # predicted_targets = self.qnetwork_local(self.graphlist[0], train_nfeat, states[0], actions[0])

        # print("predicted_targets raw", self.qnetwork_local(states).shape)
        # print("predicted_targets processed", predicted_targets.shape)

        self.qnetwork_local1.eval()
        self.qnetwork_local2.eval()

        with torch.no_grad():
            labels_next = []
            for counts, (count_state, gindex) in enumerate(zip(next_states, gindexs)):
                gindex = int(gindex.item())
                candnodes = self.candidatenodelist[gindex].copy()
                candnodes = [ele for ele in candnodes if ele not in count_state]
                candnodes = torch.tensor(candnodes).to(device)

                # temp_label = []
                for counta, count_action in enumerate(candnodes):

                    actions_qlocal1 = self.qnetwork_local1(self.graphlist[gindex], self.graphlist[gindex].ndata['feature'], count_state, count_action)
                    actions_qlocal2 = self.qnetwork_local2(self.graphlist[gindex], self.graphlist[gindex].ndata['feature'], count_state, count_action)

                    if counta == 0:
                        actions_qlocal = self.alpha*actions_qlocal1 + (1 - self.alpha)*actions_qlocal2
                    else:
                        actions_qlocal = torch.cat([actions_qlocal, self.alpha*actions_qlocal1 + (1 - self.alpha)*actions_qlocal2], dim=0)

                # single greedy action from next state
                actions_qlocal = torch.argmax(actions_qlocal)
                # q value of next state for each of the objectives
                temp_label1 = self.qnetwork_target1(self.graphlist[gindex], self.graphlist[gindex].ndata['feature'], count_state, actions_qlocal)
                temp_label2 = self.qnetwork_target2(self.graphlist[gindex], self.graphlist[gindex].ndata['feature'], count_state, actions_qlocal)
                # temp_label = torch.reshape(torch.max(temp_label), (1,1))

                if counts == 0:
                    labels_next1 = temp_label1
                    labels_next2 = temp_label2
                else:
                    labels_next1 = torch.cat([labels_next1, temp_label1], dim=0)
                    labels_next2 = torch.cat([labels_next2, temp_label2], dim=0)

                try:
                    del temp_label1, temp_label2, actions_qlocal
                except:
                    pass

        self.qnetwork_local1.train()
        self.qnetwork_local2.train()

        # .detach() ->  Returns a new Tensor, detached from the current graph.
        # labels = torch.tensor([rewards[ind] + (gamma*labels_next[ind]*(1-dones[ind])) for ind in range(int(states.shape[0])) ])
        # labels = torch.tensor([rewards[ind] + (gamma*labels_next[ind]*(1-dones[ind])) for ind in range(int(states.shape[0])) ])
        # target labels for Q network local 1
        labels1 = rewards1 + torch.mul( (torch.mul(labels_next1, gamma)),(1-dones))
        # target labels for Q network local 2
        labels2 = rewards2 + torch.mul( (torch.mul(labels_next2, gamma)),(1-dones))
        # predicted_targets = torch.tensor(predicted_targets)

        loss1 = criterion(predicted_targets1, labels1).to(device)
        loss2 = criterion(predicted_targets2, labels2).to(device)

        self.trainloss1.append(loss1.item())
        self.trainloss2.append(loss2.item())

        self.optimizer1.zero_grad()
        self.optimizer2.zero_grad()

        loss1.backward()
        loss2.backward()

        self.optimizer1.step()
        self.optimizer2.step()

        # ------------------- update target network ------------------- #

        # self.soft_update(self.qnetwork_local1, self.qnetwork_target1,TAU)
        # self.soft_update(self.qnetwork_local2, self.qnetwork_target2,TAU)

    def soft_update(self, local_model, target_model, tau):

        """Soft update model parameters.
        θ_target = τ*θ_local + (1 - τ)*θ_target

        Params
        =======
            local model (PyTorch model): weights will be copied from
            target model (PyTorch model): weights will be copied to
            tau (float): interpolation parameter

        """
        for target_param, local_param in zip(target_model.parameters(),
                                           local_model.parameters()):
            target_param.data.copy_(tau*local_param.data + (1-tau)*target_param.data)

class ReplayBuffer:

    """Fixed -size buffer to store experience tuples."""
    
    def __init__(self, buffer_size, batch_size, seed):
        """Initialize a ReplayBuffer object.
        
        Params
        ======
            action_size (int): dimension of each action
            buffer_size (int): maximum size of buffer
            batch_size (int): size of each training batch
            seed (int): random seed
        """
        
        # self.action_size = action_size
        self.memory = deque(maxlen=buffer_size)
        self.batch_size = batch_size
        self.experiences = namedtuple("Experience", field_names=["state",
                                                               "action",
                                                               "reward",
                                                               "next_state",
                                                               "done",
                                                                "gindex",
                                                                 "reward1",
                                                                 "reward2"])
        self.seed = random.seed(seed)
        
    def add(self,state, action, reward, next_state,done, gindex,reward1,reward2):
        """Add a new experience to memory."""
        e = self.experiences(state,action,reward,next_state, done, gindex, reward1,reward2)
        self.memory.append(e)

    def sample(self, batch_size=BATCH_SIZE):

        """Randomly sample a batch of experiences from memory"""
        experiences = random.sample(self.memory, k=batch_size)
        
        # states = torch.tensor(torch.tensor([e.state for e in experiences if e is not None])).float().to(device)
        # states = torch.from_numpy(np.vstack([e.state.item() for e in experiences if e is not None])).float().to(device)
        # states = np.array([torch.tensor(e.state).to(device) for e in experiences if e is not None])
        temp = [(e.state) for e in experiences if e is not None]

        max_cols = max([len(batch) for batch in temp ])
        # NEEDS CHANGES IF AGGREGATION OF STATE VECTOR FUNCTION CHNAGES FROM MAXIMUM FUNCTION
        padded = [batch + [batch[0]]*(max_cols - len(batch)) for batch in temp]

        states = torch.tensor(padded).to(device)

        # actions = torch.from_numpy(np.vstack([e.action for e in experiences if e is not None])).long().to(device)
        actions = torch.from_numpy(np.vstack([e.action.item() for e in experiences if e is not None])).long().to(device)

        rewards = torch.from_numpy(np.vstack([e.reward for e in experiences if e is not None])).float().to(device)
        rewards1 = torch.from_numpy(np.vstack([e.reward1 for e in experiences if e is not None])).float().to(device)
        rewards2 = torch.from_numpy(np.vstack([e.reward2 for e in experiences if e is not None])).float().to(device)

        # gindex
        gindexs = torch.from_numpy(np.vstack([e.gindex for e in experiences if e is not None])).float().to(device)

        # next_states = torch.from_numpy(np.vstack([e.next_state for e in experiences if e is not None])).float().to(device)
        # next_states = np.array([torch.tensor(e.next_state).to(device) for e in experiences if e is not None])

        tempns = [(e.next_state) for e in experiences if e is not None]

        max_cols = max([len(batch) for batch in tempns])
        # NEEDS CHANGES IF AGGREGATION OF STATE VECTOR FUNCTION CHNAGES FROM MAXIMUM FUNCTION
        paddedns = [batch + [batch[0]]*(max_cols - len(batch)) for batch in tempns]
        next_states = torch.tensor(paddedns).to(device)

        dones = torch.from_numpy(np.vstack([e.done for e in experiences if e is not None]).astype(np.uint8)).float().to(device)
        
        return (states,actions,rewards,next_states,dones, gindexs, rewards1, rewards2)

    def get_memory(self):

        """ sample a wholebatch of experiences from memory"""
        experiences = self.memory

        # states = torch.tensor(torch.tensor([e.state for e in experiences if e is not None])).float().to(device)
        # states = torch.from_numpy(np.vstack([e.state.item() for e in experiences if e is not None])).float().to(device)
        # states = np.array([torch.tensor(e.state).to(device) for e in experiences if e is not None])
        states = [(e.state) for e in experiences if e is not None]

        # max_cols = max([len(batch) for batch in temp])
        # NEEDS CHANGES IF AGGREGATION OF STATE VECTOR FUNCTION CHNAGES FROM MAXIMUM FUNCTION
        # padded = [batch + [batch[0]] * (max_cols - len(batch)) for batch in temp]

        # states = torch.tensor(temp).to(device)

        # actions = torch.from_numpy(np.vstack([e.action for e in experiences if e is not None])).long().to(device)
        actions = torch.from_numpy(np.vstack([e.action.item() for e in experiences if e is not None])).long().to(device)

        rewards = torch.from_numpy(np.vstack([e.reward for e in experiences if e is not None])).float().to(device)
        rewards1 = torch.from_numpy(np.vstack([e.reward1 for e in experiences if e is not None])).float().to(device)
        rewards2 = torch.from_numpy(np.vstack([e.reward2 for e in experiences if e is not None])).float().to(device)

        # gindex
        gindexs = torch.from_numpy(np.vstack([e.gindex for e in experiences if e is not None])).float().to(device)

        # next_states = torch.from_numpy(np.vstack([e.next_state for e in experiences if e is not None])).float().to(device)
        # next_states = np.array([torch.tensor(e.next_state).to(device) for e in experiences if e is not None])

        next_states = [(e.next_state) for e in experiences if e is not None]

        # max_cols = max([len(batch) for batch in tempns])
        # NEEDS CHANGES IF AGGREGATION OF STATE VECTOR FUNCTION CHNAGES FROM MAXIMUM FUNCTION
        # paddedns = [batch + [batch[0]] * (max_cols - len(batch)) for batch in tempns]
        # next_states = torch.tensor(tempns).to(device)

        dones = torch.from_numpy(np.vstack([e.done for e in experiences if e is not None]).astype(np.uint8)).float().to(
            device)

        return (states, actions, rewards, next_states, dones, gindexs, rewards1, rewards2)

    def update_avgreward(self, avg_reward):
        """Randomly sample a batch of experiences from memory"""
        # experiences = random.sample(self.memory, k=batch_size)
        experiences = self.memory
        max_reward = avg_reward.copy()
        for cgraph in range(6):
            for cstate in range(1,5):
                listexp = [ind for ind in experiences if len(ind.state)== cstate and ind.gindex== cgraph ]
                if len(listexp) == 0:
                    continue
                max_reward[cgraph, cstate-1] = np.max([e.reward for e in listexp])

        return max_reward

    def __len__(self):
        """Return the current size of internal memory."""
        return len(self.memory)

