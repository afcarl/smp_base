"""A leaky integrator rate-coded reservoir class"""

# TODO
# - switch to matrix data types?
# - simplify and clean up
# - FIXME: intrinsic plasticity: input layer, reservoir layer
# - FIXME: correlated exploration noise
# - FIXME: multiple timescales / tau
# - FIXME: pooling mechanism / competition

# Authors
# - Oswald Berthold, Aleke Nolte

import sys, time, argparse
# from jpype import startJVM, getDefaultJVMPath, JPackage, shutdownJVM, JArray, JDouble

import numpy as np
import numpy.linalg as LA
import scipy.sparse as spa
import matplotlib.pyplot as pl
from matplotlib import gridspec
import rlspy

# if "/home/src/QK/smp/neural" not in sys.path:
#     sys.path.insert(0, "/home/src/QK/smp/neural")
from learners import GHA


############################################################
# utility functions
def create_matrix_reservoir(N, p):
    """Create an NxN reservoir recurrence matrix with density p"""
    M = spa.rand(N, N, p)
    M = M.todense()
    tmp_idx = M != 0
    tmp = M[tmp_idx]
    tmp_r = np.random.normal(0, 1, size=(tmp.shape[1],))
    M[tmp_idx] = tmp_r
    # print "type(M)", type(M)
    # print "M.shape", M.shape
    # M = np.array(M * self.g * self.scale)
    return np.array(M).copy()
    # return spa.bsr_matrix(M)

def normalize_spectral_radius(M, g):
    """Normalize the spectral radius of matrix M to g"""
    # compute eigenvalues
    [w,v] = LA.eig(M)
    # get maximum absolute eigenvalue
    lae = np.max(np.abs(w))
    # print "lae pre", lae
    # normalize matrix
    M /= lae
    # scale to desired spectral radius
    M *= g
    # print "type(M)", type(M)
    # print "M.shape", M.shape
    # # check for scaling
    # [w,v] = LA.eig(self.M)
    # lae = np.max(np.abs(w))
    # print "lae post", lae

################################################################################
# input matrix creation
def res_input_matrix_random_sparse(idim = 1, odim = 1, sparsity=0.1):
    """create a sparse input matrix"""
    p_wi = sparsity
    wi_ = spa.rand(odim, idim, p_wi)
    # print "sparse wi", wi_
    wi = wi_.todense()
    tmp_idx = wi != 0
    tmp = wi[tmp_idx]
    # tmp_r = np.random.normal(0, 1, size=(tmp.shape[1],))
    tmp_r = np.random.uniform(-1, 1, size=(tmp.shape[1],))
    wi[tmp_idx] = tmp_r
    return np.asarray(wi)

def res_input_matrix_disjunct_proj(idim = 1, odim = 1):
    """create an input matrix that projects inputs onto disjunct regions of hidden space"""
    # all matrices tensor
    wi_ = np.zeros((idim, odim, idim))
    numhiddenperinput = odim / idim
    # for each input create a matrix
    # sum all matrices up
    for i in range(idim):
        # print wi_[i]
        offset = (i * numhiddenperinput)
        wi_[i,offset:offset+numhiddenperinput,i] = np.random.uniform(-1, 1, (numhiddenperinput, ))
    wi = np.sum(wi_, axis=0)
    return wi

class LearningRules(object):
    def __init__(self):
        self.loss = None
        self.e = None

    ############################################################
    # learning rule: FORCE
    # David Sussillo, L.F. Abbott, Generating Coherent Patterns of
    # Activity from Chaotic Neural Networks, Neuron, Volume 63, Issue
    # 4, 27 August 2009, Pages 544-557, ISSN 0896-6273,
    # http://dx.doi.org/10.1016/j.neuron.2009.07.018. (http://www.sciencedirect.com/science/article/pii/S0896627309005479)
    # Keywords: SYSNEURO
    def learnFORCE_update_P(self, P, r):
        """Perform covariance update for FORCE learning"""
        k = np.dot(P, r)
        rPr = np.dot(r.T, k)
        c = 1.0/(1.0 + rPr)
        P = P - np.dot(k, (k.T*c))
        return (P, k, c)
        
    def learnFORCE(self, target, P, k, c, r, z, channel):
        """FORCE learning rule for reservoir online supervised learning"""
        # compute error
        e = z - target
        # compute weight update from error times k
        dw = -e.T * k * c
        return dw
    
    def learnFORCEmdn(self, target, P, k, c, r, z, channel, x):
        """FORCE learning rule for reservoir online supervised learning"""
        # compute error
        # e = z - target
        
        self.e = self.mdn_loss(x, z, target)
        # print "e", self.e.T
        # compute weight update from error times k
        dw = -self.e.T * k * c
        return dw

    def mixture(self, mu, sig, ps):
        # print "sum(ps)", np.sum(ps)
        # print "mu", mu, "sig", sig, "ps", ps
        compidx = np.where(np.random.multinomial(1, ps) == 1.0)[0][0]
        # print "sig[compidx]", np.abs(sig[compidx])
        y = np.random.normal(mu[compidx], np.abs(sig[compidx]) + np.random.uniform(0, 1e-3, size=sig[compidx].shape))
        return y

    def mdn_loss(self, x, z, y, loss_only = False):
        mixcomps = 3
        # data in X are columns
        # print "z.shape", z.shape
        # forward pass
        # h = np.tanh(np.dot(m['Wxh'], x) + m['bxh'])
        # self.r
        # predict mean
        # mu = np.dot(m['Whu'], h) + m['bhu']
        mu = z[:mixcomps,[0]]
        # print("mu.shape", mu.shape)
        #pl.clf()
        #pl.plot(mu)
        #pl.draw()
        # predict log variance
        # logsig = np.dot(m['Whs'], h) + m['bhs']
        logsig = z[mixcomps:(2*mixcomps),[0]]
        sig = np.exp(logsig)
        # predict mixture priors
        # piu = np.dot(m['Whp'], h) + m['bhp'] # unnormalized pi
        piu = z[(2*mixcomps):,[0]]
        pi = self.softmax(piu)
        # print mu, sig, pi
        # compute the loss: mean negative data log likelihood
        k,n = mu.shape # number of mixture components
        n = float(n)
        # print "(y-mu).shape", (y-mu).shape
        ps = np.exp(-((y - mu)**2)/(2*sig**2))/(sig*np.sqrt(2*np.pi))
        pin = ps * pi
        lp = -np.log(np.sum(pin, axis=0, keepdims=True))
        loss = np.sum(lp) / n
        self.loss = loss
        # print "lp", lp
        if loss_only: # do something smarter here, change calling foo and return both errors and loss
            return loss
        
        # # compute the gradients on nn outputs
        # grad = {}
        # gammas are pi_i's in bishop94
        gammas = pin / np.sum(pin, axis=0, keepdims = True)
        dmu = gammas * ((mu - y)/sig**2) / n
        dlogsig = gammas * (1.0 - (y-mu)**2/(sig**2)) / n
        dpiu = (pi - gammas) / n
        # print dmu.shape, dlogsig.shape, dpiu.shape
        # print "|dmu| = %f" % (np.linalg.norm(dmu))
        return np.vstack((dmu, dlogsig, dpiu))
    
    def softmax(self, x):
        # softmaxes the columns of x
        #z = x - np.max(x, axis=0, keepdims=True) # for safety
        e = np.exp(x)
        en = e / np.sum(e, axis=0, keepdims=True)
        return en
        
class Reservoir(object):
    def __init__(self, N=100, p = 0.1, g = 1.2, alpha = 1.0, tau = 0.1,
                 input_num=1, output_num=1, input_scale = 0.05,
                 feedback_scale = 0.01, bias_scale = 0.,
                 eta_init=1e-5, theta = 1e-1, theta_state = 1e-2,
                 nonlin_func=np.tanh,
                 sparse=True,
                 ip=False,
                 coeff_a = 0.2,
                 mtau=False):
        # reservoir size
        self.N = N
        # connection density
        self.p = p
        # reservoir weight gain
        self.g = g
        # leak rate
        self.mtau = mtau
        if self.mtau:
            # self.tau = np.exp(np.random.uniform(-10, -2, (self.N, 1)))
            self.tau = np.exp(np.random.uniform(-8, -0.5, (self.N, 1)))
        else:
            self.tau = tau
        self.alpha = alpha
        # scale gain to spectral radius lambda
        self.scale = 1.0/np.sqrt(self.p*self.N)
        # reservoir connection matrix
        self.M = create_matrix_reservoir(self.N, self.p)

        normalize_spectral_radius(self.M, self.g)
        self.M = spa.csr_matrix(self.M)
        
        # inputs and input weight matrix
        self.input_num = input_num
        self.wi_amp = input_scale
        # self.wi = np.random.uniform(-self.wi_amp, self.wi_amp, (self.N, self.input_num))
        self.wi = np.random.normal(0, self.wi_amp, (self.N, self.input_num))
        
        # readout feedback term
        self.output_num = output_num
        self.wf_amp = feedback_scale
        self.wf = np.random.uniform(-self.wf_amp, self.wf_amp, (self.N, self.output_num))
        # outputs and readout weight matrix
        self.wo = np.zeros((self.N, self.output_num));

        # initialize states to zeros
        self.u = np.zeros(shape=(self.input_num, 1))
        self.x = np.zeros(shape=(self.N, 1))
        self.r = np.zeros(shape=(self.N, 1))
        self.z = np.zeros(shape=(self.output_num, 1))
        self.zn = np.zeros((self.output_num, 1))
        # initialize states randomly
        # self.init_states_random()
        # bias
        self.bias = np.random.uniform(-1., 1., size=self.x.shape)
        self.bias_scale = bias_scale
        
        # rewards
        self.perf = np.zeros((self.output_num, 1))
        # self.perf_t = np.zeros((self.output_num, self.simtime_len))
        self.mdltr = np.zeros((self.output_num, 1))
        # self.mdltr_t = np.zeros((self.output_num, self.simtime_len))
        self.zn_lp = np.zeros((self.output_num, 1))
        # self.zn_lp_t = np.zeros((self.output_num, self.simtime_len))
        self.perf_lp = np.zeros((self.output_num, 1))
        # self.perf_lp_t = np.zeros((self.output_num, self.simtime_len))
        # self.coeff_a = 0.2
        self.coeff_a = coeff_a

        # initial learning rate and decay time constant
        self.eta_init = eta_init
        self.eta_tau = 200000.

        # exploration noise
        self.set_theta(theta)
        # noise filtering
        self.nu_ = np.zeros_like(self.z)
        # self.theta = theta # 1/10.
        # # different exploration noise amplitudes for different output dimensions
        # self.theta_amps = np.ones(shape=(self.output_num, 1)) * self.theta
        # state noise amplitude
        # self.theta_state = 0 #1/1000.
        self.theta_state = theta_state # 1/20.

        # FORCE stuff
        self.P = (1.0/self.alpha)*np.eye(self.N)
    
        # nonlinearity
        self.nonlin_func = nonlin_func


        # intrinsic plasticity
        self.ip = ip
        self.ip_a = np.random.uniform(-1e-1, 1e-1, (self.input_num, 1))
        self.ip_b = np.random.uniform(-1e-1, 1e-1, (self.input_num, 1))
        self.ip_eta = np.ones((self.input_num,1)) * 1e-5
        self.ip_mu  = np.zeros((self.input_num, 1))
        self.ip_var = np.ones((self.input_num, 1)) * 0.01
        # for whitening
        # self.u_mean = np.zeros_like(self.u)
        # self.u_var  = np.zeros_like(self.u)
        self.u_mean = np.random.uniform(-0.1, 0.1, self.u.shape)
        self.u_var  = np.random.uniform(-0.1, 0.1, self.u.shape)

    # setters
    def set_theta(self, theta):
        """Set exploration noise amplitude (theta) and theta_amps"""
        self.theta = theta
        self.theta_amps = np.ones(shape=(self.output_num, 1)) * self.theta
        # print "res: theta_amps", self.theta_amps
        


    ############################################################
    # save network
    def save(self, filename=""):
        from cPickle import Pickler
        if filename == "":
            timestamp = time.strftime("%Y-%m-%d-%H%M%S")
            filename = "reservoir-%s.bin" % timestamp
        f = open(filename,'wb')
        p = Pickler(f, 2)
        p.dump(self.__dict__)
        f.close()
        return
        

    ############################################################
    # load network (restore from file)
    # @classmethod
    def load(self, filename):
        from cPickle import Unpickler
        print "reservoirs.py: loading %s" % filename
        f = open(filename,'rb')
        u = Unpickler(f)
        tmp_dict = u.load()
        f.close()
        self.__dict__.update(tmp_dict)

    ############################################################
    # initialize states randomly
    def init_states_random(self):
        self.x = 0.5 * np.random.normal(size=(self.N, 1))
        self.z = 0.5 * np.random.normal(size=(self.output_num, 1))

    ############################################################
    # reset states to zero
    def reset_states(self):
        self.x = np.zeros(shape=(self.N, 1))
        self.z = np.zeros(shape=(self.output_num, 1))


    ############################################################
    # initialize output weights randomly
    def init_wo_random(self, mu=0., std=0.001):
        self.wo = np.random.normal(mu, std, (self.N, self.output_num))

    ############################################################
    # initialize output weights to zero
    def init_wo_zero(self):
        self.wo = np.zeros((self.N, self.output_num))

    ############################################################
    # initialize input weights to I
    def init_wi_identity(self):
        # self.wo = np.eye((self.N, self.output_num))
        self.wi = np.eye((self.input_num)) 
        
    ############################################################
    # initialize input weights to ones
    def init_wi_ones(self):
        # self.wo = np.eye((self.N, self.output_num))
        self.wi = np.ones((self.N, self.input_num)) * self.wi_amp

    def ip_input_layer(self, u):
        # FIXME: self.ip_a * u ?
        u = u.reshape((self.input_num, 1))
        # print self.ip_a.shape, u.shape
        u_tmp = np.tanh(self.ip_a * u + self.ip_b)
        # print u_tmp.shape
        db = -self.ip_eta * ((-self.ip_mu/self.ip_var) + (u_tmp / self.ip_var) * (2 * self.ip_var + 1 - u_tmp**2 + self.ip_mu * u_tmp))
        # print "db", db.shape, db
        da = (self.ip_eta/self.ip_a) + (db * u)
        # print "da", da.shape, da
        self.ip_b += db
        self.ip_a += da
        # print "da,db norm", LA.norm(self.ip_a, 2), LA.norm(self.ip_b, 2), LA.norm(da, 2), LA.norm(db, 2)
        # print u_tmp.shape
        return u_tmp

    def ip_input_layer_whiten(self, u):
        self.u_mean = 0.999 * self.u_mean + 0.001 * u
        self.u_var = 0.999 * self.u_var + 0.001 * np.sqrt(np.square(u - self.u_mean))
        # print "u_mean", self.u_mean
        # print "u_var", self.u_var
        # print np.linalg.norm(self.u_mean)
        # print np.linalg.norm(self.u_var)
        # print np.linalg.norm(u - self.u_mean)
        u_out = (u - self.u_mean)/self.u_var
        # print np.linalg.norm(u_out)
        return u_out
        # return (0.5 * u - 0.5 * self.u_mean) # / self.u_var

    ############################################################
    # execute Reservoir
    def execute(self, u):
        # FIXME: check for proper shape of elements
        # FIXME: guard for proper shapes (atleast_..., ...)
        # collect the terms
        zeta_state = np.random.uniform(-self.theta_state, self.theta_state, size=self.x.shape)
        # state
        x_tp1 = (1.0 - self.tau) * self.x
        # reservoir
        # r_tp1 = np.dot(self.M, self.r)
        r_tp1 = self.M.dot(self.r)
        # r_tp1 = self.r
        # r_tp1 = np.dot(self.M, self.r)
        # readout feedback
        f_tp1 = np.dot(self.wf, self.zn)
        # f_tp1 = np.dot(self.wf, self.zn)
        # print x_tp1, r_tp1, f_tp1
        # input
        if self.ip:
            self.u = self.ip_input_layer(u)
            # print self.u
        else:
            self.u = u
        u_tp1 = np.reshape(np.dot(self.wi, self.u), (self.x.shape))
        # bias
        b_tp1 = self.bias * self.bias_scale
        # print "x_tp1", x_tp1.shape
        # print "r_tp1", r_tp1.shape
        # print "f_tp1", f_tp1.shape
        # print "u_tp1", u_tp1.shape
        # print "zn_tp1", self.zn.shape

        # update state
        self.x = x_tp1 + self.tau * (r_tp1 + f_tp1 + u_tp1 + b_tp1)
        # self.r = self.tau * np.tanh(r_tp1 + f_tp1 + u_tp1 + b_tp1)
        # self.x = x_tp1 + self.r
        # self.r = np.tanh(self.x) + zeta_state
        self.r = self.nonlin_func(self.x) + zeta_state
        # print "self.x", self.x.shape
        # print "self.r", self.r, self.r.shape

        # print "shapes", self.wo.shape, self.r.shape
        self.z = np.dot(self.wo.T, self.r)
        # self.zn = self.z + np.random.normal(0, self.theta, size=(self.z.shape))
        # generate standard normal noise per output dimension
        nu_tmp = np.random.normal(0, 1.0, size=(self.z.shape))
        # nu_tmp = np.random.pareto(1.2, size=(self.z.shape))
        # nu_tmp = ((np.random.binomial(1, 0.5) - 0.5) * 2) * np.random.pareto(1.5, self.z.shape) #  * self.sigma_expl
        # multiply with noise amplitudes
        nu = nu_tmp * self.theta_amps
        self.nu_ = 0.8 * self.nu_ + 0.2 * nu
        # print "nu", nu
        # apply to noisy readout
        self.zn = self.z + nu
        # self.zn = self.z + self.nu_
        
        self.zn_lp = self.zn_lp * (1-self.coeff_a) + self.zn * self.coeff_a
        # print "Wo", self.wo.T.shape
        # print "self.r", self.r.shape
        # print "z", self.z.shape, self.z, self.zn.shape, self.zn
        # return clean output, no noise
        return self.z

    # ############################################################
    # # learn: RLS
    # # FIXME: rlspy
    # # function [th,p] = rolsf(x,y,p,th,lam)
    # # % function [th,p] = rolsf(x,y,p,th,lam)
    # # %    Recursive ordinary least squares for single output case,
    # # %       including the forgetting factor, lambda.
    # # %    Enter with x = input, y = output, p = covariance, th = estimate, 
    # # lam = forgetting factor
    # # %
    # #      a=p*x;
    # #      g=1/(x'*a+lam);
    # #      k=g*a;
    # #      e=y-x'*th;
    # #      th=th+k*e;
    # #      p=(p-g*a*a')/lam;
    # def learnRLS(self, target):
    #     lam = 0.98
    #     a = np.dot(self.P, self.r)
    #     g = 1 / (np.dot(self.r, a) + lam)
    #     k = np.dot(g, a)
    #     e = target - self.z[:,0] # np.dot(self.r, self.wo)
    #     dw = np.dot(k, e)
    #     self.wo += dw
    #     self.P = (self.P-np.dot(g, np.dot(a, a.T)))/lam

    # def dwFORCE(self, P, r, z, target):

    # ############################################################
    # # learn: FORCE, EH, recursive regression (RLS)?
    # def learnFORCE(self, target):
    #     # get some target
    #     # use FORCE to calc dW
    #     # use EH to calc dW
    #     k = np.dot(self.P, self.r)
    #     rPr = np.dot(self.r.T, k)
    #     c = 1.0/(1.0 + rPr)
    #     # print "r.shape", self.r.shape
    #     # print "k.shape", k.shape, "P.shape", self.P.shape, "rPr.shape", rPr.shape, "c.shape", c.shape
    #     self.P = self.P - np.dot(k, (k.T*c))
        
    #     for i in range(self.output_num):
    #         # print "self.P", self.P
    #         # print "target.shape", target.shape
    #         e = self.z[i,0] - target[i,0]
    #         # print "error e =", e, self.z[i,0]

    #         # print "err", e, "k", k, "c", c
    #         # print "e.shape", e.shape, "k.shape", k.shape, "c.shape", c.shape
    #         # dw = np.zeros_like(self.wo)
    #         dw = -e * k * c
    #         # dw = -e * np.dot(k, c)
    #         # print "dw", dw.shape
    #         # print "shapes", self.wo.shape, dw.shape # .reshape((self.N, 1))
    #         # print i
    #         # print "shapes", self.wo[:,0].shape, dw[:,0].shape # .reshape((self.N, 1))
    #         # print "types", type(self.wo), type(dw)
    #         self.wo[:,i] += dw[:,0]
    #         # self.wo[:,i] = self.wo[:,i] + dw[:,0]
    #         # self.wo[:,i] += dw[:]
    #     # print "FORCE", LA.norm(self.wo, 2)
    #     # return 0

    ############################################################
    # learn: FORCE, EH, recursive regression (RLS)?
    def learnFORCE(self, target):
        # update statistics
        k = np.dot(self.P, self.r)
        rPr = np.dot(self.r.T, k)
        c = 1.0/(1.0 + rPr)
        self.P = self.P - np.dot(k, (k.T*c))

        # compute error
        e = self.z - target
        # compute dw
        dw = -e.T * k * c
        # apply update
        self.wo += dw
                        
    def learnRLSsetup(self,wo_init, P0_init):
        # Attention! not using function parameters
         
        #self.rls_E = rlspy.data_matrix.Estimator(np.zeros(shape=(self.N, 1)) ,(1.0/self.alpha)*np.eye(self.N))
        #self.rls_E = rlspy.data_matrix.Estimator(np.random.uniform(0, 0.0001, size=(self.N, 1)) , np.eye(self.N))
        if wo_init==None  and   P0_init==None :
          print ("using random initialization for RLS setup ")
          # self.rls_E = rlspy.data_matrix.Estimator(np.random.uniform(0, 0.1, size=(self.N, 1)) , np.eye(self.N))
          self.rls_E = rlspy.data_matrix.Estimator(np.random.uniform(0, 0.01, size=(self.N, 1)) , np.eye(self.N))
          # self.wo = np.random.uniform(-1e-4,1e-4, size=(self.N, self.output_num))
          self.wo = np.zeros((self.N, self.output_num))
        else:
          print ('taking arguments as initialization for RLS setup')
          self.wo = wo_init
          self.rls_E = rlspy.data_matrix.Estimator(P0_init[0], P0_init[1])

        #self.wo = np.random.uniform(-1e-3,1e-3, size=(self.N, self.output_num))
        #self.wo = np.random.uniform(0,1, size=(self.N, self.output_num))

    def learnRLS(self, target):
        # print "%s.learnRLS, target.shape = %s" % (self.__class__.__name__, target.shape)
        self.rls_E.update(self.r.T, target.T, self.theta_state) 
        self.wo = self.rls_E.x
        
    def learnEH(self, target):
        """Exploratory Hebbian learning rule. This function computes the reward from the exploration result and modulates the Hebbian update with that reward, which can be binary or continuous. The exploratory part is happening in execute() by adding gaussian noise centered on current prediction."""
        eta = self.eta_init # 0.0003
        
        self.perf = -np.square(self.zn - target)

        # binary modulator
        mdltr = (np.clip(self.perf - self.perf_lp, 0, 1) > 0) * 1.0
        # # continuous modulator
        # vmdltr = (self.perf - self.perf_lp)
        # vmdltr /= np.sum(np.abs(vmdltr))
        # OR  modulator
        # mdltr = np.ones_like(self.zn) * np.clip(np.sum(mdltr), 0, 1)
        # AND modulator
        mdltr = np.ones_like(self.zn) * (np.sum(mdltr) > 1)

        # compute dw
        dw = eta * np.dot(self.r, np.transpose((self.zn - self.zn_lp) * mdltr))
        # update weights
        self.wo += dw
        # update performance prediction
        self.perf_lp = ((1 - self.coeff_a) * self.perf_lp) + (self.coeff_a * self.perf)
        
    # def learnPISetup(self):
        
    #     self.piCalcClassD = JPackage("infodynamics.measures.discrete").PredictiveInformationCalculatorDiscrete
    #     self.piCalcClass = JPackage("infodynamics.measures.continuous.kernel").MutualInfoCalculatorMultiVariateKernel
    #     self.entCalcClass = JPackage("infodynamics.measures.continuous.kernel").EntropyCalculatorKernel
    #     self.base = 20
    #     self.piCalcD = self.piCalcClassD(self.base,3)
    #     # self.aisCalcD = self.aisCalcClassD(self.base,5)
    #     self.piCalc = self.piCalcClass();
    #     self.entCalc = self.entCalcClass();    

    def perfVar(self, x):
        # self.eta_init = 1.2e-3
        # self.eta_init = 2e-3

        # em.plot_pi_discrete_cont()
        # em.calc_pi_cont_windowed()
        # em.plot_pi_cont_windowed()
        # em.calc_global_entropy()
        # em.calc_local_entropy()
        # em.calc_global_entropy_cont()
        # em.plot_measures()
        # em.calc_pi_discrete()
        # pi = np.mean(em.pi)
        # em.calc_pi_discrete_avg()
        # pi = em.pi
        perf = np.var(x)
        
        self.perf = np.array([perf]).reshape((self.output_num, 1))
        
    def learnEHPerf(self):
        eta = self.eta_init
        # print "perf", self.perf
        for i in range(self.output_num):
            if self.perf[i,0] > self.perf_lp[i,0]:
                # print "mdltr", self.perf[i,0], self.perf_lp[i,0]
                self.mdltr[i,0] = 1
            else:
                self.mdltr[i,0] = 0
            dW = eta * (self.zn[i,0] - self.zn_lp[i,0]) * self.mdltr[i,0] * self.r
            # dW = eta * (self.zn[i,0] - self.zn_lp[i,0]) * -self.perf * self.r
            # print dW
            # print dW.shape, self.x.shape, self.wo[:,i].shape
            # print np.reshape(dW, (self.N, )).shape
            self.wo[:,i] += dW[:,0]
            # self.wo[:,i] += np.reshape(dW, (self.N, ))
            
        self.perf_lp = ((1 - self.coeff_a) * self.perf_lp) + (self.coeff_a * self.perf)
        
                        
    # def learnPI(self, x):
    #     eta = self.eta_init
        
    #     # dmax = np.max(x)
    #     # dmin = np.min(x)
    #     # # print self.dmax, self.dmin
    #     # # bins = np.arange(self.dmin, self.dmax, 0.1)
    #     # bins = np.linspace(dmin, dmax, 20) # FIXME: determine binnum
    #     # # print "x.shape", x.shape
    #     # x_d = np.digitize(x[0,:], bins).reshape(x.shape)
    #     # # print "x_d.shape", x_d.shape
    #     # # pi = list(self.piCalcD.computeLocal(x_d))
    #     # pi = self.piCalcD.computeAverageLocal(x_d)
    #     # # print pi
    #     # # base = np.max(x_d)+1 # 1000
        
    #     # # compute PI
    #     # self.piCalc.setProperty("NORMALISE", "true"); # Normalise the individual variables
    #     # self.piCalc.initialise(1, 1, 0.25); # Use history length 1 (Schreiber k=1), kernel width of 0.5 normalised units
    #     # # print "x", x.shape
    #     # src = np.atleast_2d(x[0,0:-100]).T # start to end - 1
    #     # dst = np.atleast_2d(x[0,100:]).T # 1 to end
    #     # # print "src, dst", src, dst
    #     # # print "src, dst", src.shape, dst.shape
    #     # self.piCalc.setObservations(src, dst)
    #     # pi = self.piCalc.computeAverageLocalOfObservations()
        
        
    #     # compute differential entropy
    #     # self.entCalc.setProperty("NORMALISE", "true"); # Normalise the individual variables
    #     self.entCalc.initialise(0.5); # Use history length 1 (Schreiber k=1), kernel width of 0.5 normalised units
    #     # print "x", x.shape
    #     # src = np.atleast_2d(x[0,0:-10]).T # start to end - 1
    #     # dst = np.atleast_2d(x[0,10:]).T # 1 to end
    #     # print "src, dst", src, dst
    #     # print "src, dst", src.shape, dst.shape
    #     self.entCalc.setObservations(JArray(JDouble, 1)(x.T))
    #     pi = self.entCalc.computeAverageLocalOfObservations()
        
    #     self.perf = np.array([pi]).reshape((self.output_num, 1))
        
    #     # print "perf", self.perf
    #     for i in range(self.output_num):
    #         if self.perf[i,0] > self.perf_lp[i,0]:
    #             # print "mdltr", self.perf[i,0], self.perf_lp[i,0]
    #             self.mdltr[i,0] = 1
    #         else:
    #             self.mdltr[i,0] = 0
    #         dW = eta * (self.zn[i,0] - self.zn_lp[i,0]) * self.mdltr[i,0] * self.r
    #         # dW = eta * (self.zn[i,0] - self.zn_lp[i,0]) * -self.perf * self.r
    #         # print dW
    #         # print dW.shape, self.x.shape, self.wo[:,i].shape
    #         # print np.reshape(dW, (self.N, )).shape
    #         self.wo[:,i] += dW[:,0]
    #         # self.wo[:,i] += np.reshape(dW, (self.N, ))
            
    #     self.perf_lp = ((1 - self.coeff_a) * self.perf_lp) + (self.coeff_a * self.perf)
    
    def learnPCA_init(self, eta=1e-4):
        # self.ro_dim = 2
        eta_gha = eta
        self.gha = GHA(eta = eta_gha, ndims = self.N, pdims = self.output_num)
        self.gha.w *= 0.1
        self.wo = self.gha.w

    def learnPCA(self):
        # resin
        # self.res.execute(resin)
        y_gha = self.gha.update(self.r)
        self.wo = self.gha.w
        self.z = y_gha
        # self.zn = self.z + np.random.normal(0, self.theta, size=(self.z.shape))
        self.zn = self.z + (np.random.normal(0, 1.0, size=(self.z.shape)) * self.theta)
        return self.z
    
    # various getters
    def get_reservoir_matrix(self):
        return self.M

    def get_input_matrix(self):
        return self.wi

    def get_feedback_matrix(self):
        return self.wf

    def get_readout_matrix(self):
        return self.wo

    def get_reservoir_size(self):
        return self.N

class Reservoir2(Reservoir):
    def __init__(self, N=100, p = 0.1, g = 1.2, alpha = 1.0, tau = 0.1,
                 input_num=1, output_num=1, input_scale=0.05,
                 feedback_scale=0.01, bias_scale=0., sparse=False,
                 eta_init=1e-3, theta = 1e-1, theta_state = 1e-2,
                 nonlin_func=np.tanh, ip=False, coeff_a=0.2):
        super(Reservoir2, self).__init__(N=N, p=p, g=g, alpha=alpha, tau=tau,
                                        input_num=input_num, output_num=output_num,
                                        input_scale=input_scale, feedback_scale=feedback_scale,
                                        bias_scale=bias_scale, eta_init=eta_init, theta = theta,
                                        theta_state = theta_state,
                                        nonlin_func=np.tanh,
                                        ip=ip, coeff_a=coeff_a)
        ############################################################
        # reservoir connection matrix
        if self.g == 0.:
            sparse = False
            print ("sparse False (g = %f)" % self.g)
        # initialize reservoir matrix with weights drawn from N(0,1)
        if sparse:
            # reservoir connection matrix: sparse version
            self.M = spa.rand(self.N, self.N, self.p)
            self.M = self.M.todense()
            tmp_idx = self.M != 0
            tmp = self.M[tmp_idx]
            tmp_r = np.random.normal(0, 1, size=(tmp.shape[1],))
            self.M[tmp_idx] = tmp_r
            # self.M = np.array(self.M * self.g * self.scale)
            # print "scale", self.scale.shape, "M", self.M.shape
            # self.M = np.array(self.M * self.g)
            self.M = np.array(self.M)
            print "M", self.M.shape
            
            # input matrix
            p_wi = 0.5
            self.wi_ = spa.rand(self.N, self.input_num, p_wi)
            # print "sparse wi", self.wi_
            self.wi = self.wi_.todense()
            # print "dense wi", self.wi
            tmp_idx = self.wi != 0
            tmp = self.wi[tmp_idx]
            # tmp_r = np.random.normal(0, 1, size=(tmp.shape[1],))
            tmp_r = np.random.uniform(-self.wi_amp, self.wi_amp, size=(tmp.shape[1],))
            self.wi[tmp_idx] = tmp_r
            # print "type(self.wi)", type(self.wi)
            self.wi = np.array(self.wi) # make sure we're numpy.ndarray and not
                                        # numpy.matrixlib.defmatrix.matrix
            # print "dense wi", self.wi
            # print "type(self.wi)", type(self.wi)
        else:
            self.M = np.random.normal(0, 1., (self.N, self.N))
            # self.wi = np.random.uniform(-self.wi_amp, self.wi_amp, (self.N, self.input_num))

        # compute eigenvalues
        [w,v] = LA.eig(self.M)
        # get maximum absolute eigenvalue
        lae = np.max(np.abs(w))
        print "lae pre", lae
        # normalize matrix
        self.M /= lae
        # scale to desired spectral radius
        self.M *= self.g

        # check for scaling
        # [w,v] = LA.eig(self.M)
        # lae = np.max(np.abs(w))
        # print "lae post", lae

        # nonlinearity
        self.nonlin_func = nonlin_func

        print "ip", self.ip        
        # # inputs and input weight matrix
        # self.wi = np.random.normal(0, self.wi_amp, (self.N, self.input_num))
        # # readout feedback term
        # self.wf = np.random.normal(0, self.wf_amp, (self.N, self.output_num))
        self.theta_amps = np.ones(shape=(self.output_num, 1)) * self.theta
        
    ############################################################
    # execute Reservoir2
    # use model from waegemann et al 2012
    def execute(self, u):
        # collect the terms
        zeta_state = np.random.uniform(-self.theta_state, self.theta_state, size=self.x.shape)
        # state
        x_tp1 = (1.0 - self.tau) * self.x
        # reservoir
        r_tp1 = np.dot(self.M, self.x)
        # r_tp1 = np.dot(self.M, self.r)
        # readout feedback
        # f_tp1 = np.dot(self.wf, self.z)
        f_tp1 = np.dot(self.wf, self.zn)
        # print x_tp1, r_tp1, f_tp1
        # input
        if self.ip:
            # print u
            self.u = self.ip_input_layer(u)
            # self.u = self.ip_input_layer_whiten(u)
            # print u
        else:
            self.u = u
        u_tp1 = np.reshape(np.dot(self.wi, self.u), (self.x.shape))
        # bias
        b_tp1 = self.bias * self.bias_scale
        # print "x_tp1", x_tp1.shape
        # print "r_tp1", r_tp1.shape
        # print "f_tp1", f_tp1.shape
        # print "u_tp1", u_tp1.shape

        # update state
        # self.x = x_tp1 + self.tau * np.tanh(r_tp1 + f_tp1 + u_tp1 + b_tp1)
        # self.x = x_tp1 + (self.tau * np.tanh(r_tp1 + f_tp1 + u_tp1 + b_tp1)) + zeta_state
        self.x = x_tp1 + (self.tau * self.nonlin_func(r_tp1 + f_tp1 + u_tp1 + b_tp1)) + zeta_state
        # self.r = self.x + zeta_state
        self.r = self.x
        # self.r = self.tau * np.tanh(r_tp1 + f_tp1 + u_tp1 + b_tp1)
        # self.x = x_tp1 + self.r
        # self.r = np.tanh(self.x) + zeta_state
        # print "self.x", self.x.shape
        # print "self.r", self.r.shape

        # print "shapes", self.wo.shape, self.r.shape
        self.z = np.dot(self.wo.T, self.r)
        # nu = np.random.normal(0, self.theta, size=(self.z.shape))
        nu = np.random.normal(0, 1.0, size=(self.z.shape))
        nu = nu * self.theta_amps
        self.zn = self.z + nu
        self.zn_lp = self.zn_lp * (1-self.coeff_a) + self.zn * self.coeff_a
        # print "Wo", self.wo.T.shape
        # print "self.r", self.r.shape
        # print "z", self.z.shape, self.z, self.zn.shape, self.zn
        return self.z

    # save network
    def save(self, filename):
        super(Reservoir2, self).save(filename)

    # load network
    def load(self, filename):
        super(Reservoir2, self).load(filename)

# usage examples
def get_frequencies(numcomp = 1):
    f_step = 0.001
    f_start = 0.001
    f_numcomp = numcomp
    f_end   = (f_numcomp + 1) * f_step
    freqs = np.linspace(f_start, f_end, f_numcomp) #.reshape((1, -1))
    # freqs_full = np.tile(freqs, (1, outdim)).T
    return freqs
                
def get_data(elen, outdim, mode="MSO_s1"):
    """Get target data from a datasource"""

    # time / index
    t = np.linspace(0, int(elen), elen)

    d_sig_freqs = np.array([1.]) * 1.0
    f_step = 0.001
    f_start = 0.001
    if mode == "MSO_s1":
        # simple
        # d_sig_freqs = np.array([0.1, 0.2]) * 0.01
        f_numcomp = 1
        f_end   = (f_numcomp + 1) * f_step
        # d_sig_freqs = np.tile(np.linspace(f_start, f_end, f_numcomp), (outdim, f_numcomp))
    elif mode == "MSO_s2":
        # simple
        # d_sig_freqs = np.array([0.1, 0.2]) * 0.01
        # d_sig_freqs = np.array([0.13, 0.26]) * 0.1
        f_numcomp = 2
        f_end   = (f_numcomp + 1) * f_step
    elif mode == "MSO_s3":
        # simple
        # d_sig_freqs = np.array([0.1, 0.2,  0.3]) * 0.02
        # d_sig_freqs = np.array([0.13, 0.26]) * 0.1
        f_numcomp = 3
        f_end   = (f_numcomp + 1) * f_step
    elif mode == "MSO_s4":
        # simple
        # f(t)=(1.3/1.5)*sin(2*pi*t)+(1.3/3)*sin(4*pi*t)+(1.3/9)*sin(6*pi*t)+(1.3/3)*sin(8*pi*t)        
        d_sig_freqs = np.array([0.1, 0.2,  0.3]) * 0.02
        # d_sig_freqs = np.array([0.13, 0.26]) * 0.1
        # 400 seconds learning
        t = t/1000.0
        print "t", t
        data = (1.3/1.5) * np.sin(2*np.pi*t) + (1.3/3) * np.sin(4*np.pi*t) + (1.3/9) * np.sin(6*np.pi*t) + (1.3/3) * np.sin(8*np.pi*t)
        data = data.reshape((1, -1)) * 0.7
        print "data.shape", data.shape
        return data
    elif mode == "MSO_c1":
        # d_sig_freqs = np.array([0.0085, 0.0174]) * 0.1
        d_sig_freqs = np.array([0.0085, 0.011]) * 0.2
        # d_sig_freqs = np.array([0.13, 0.27, 0.53, 1.077]) * 0.3
        # d_sig_freqs = [1.002, 2.004, 3.006, 4.008]
        # d_sig_freqs = np.array([0.1, 0.2, 0.3, 0.4]) * 1.
        # d_sig_freqs = np.array([0.01, 1.01, 1.02, 1.03]) * 0.1
    elif mode == "MSO_c2":
        d_sig_freqs = np.array([0.0085, 0.0174, 0.0257, 0.0343]) * 0.1
        # d_sig_freqs = np.array([0.13, 0.27, 0.53, 1.077]) * 0.3
        # d_sig_freqs = [1.002, 2.004, 3.006, 4.008]
        # d_sig_freqs = np.array([0.1, 0.2, 0.3, 0.4]) * 1.
        # d_sig_freqs = np.array([0.01, 1.01, 1.02, 1.03]) * 0.1
    elif mode == "MG": # Mackey-Glass
        import Oger
        import scipy.signal as ss
        import scipy.interpolate as si
        ds = Oger.datasets.mackey_glass(sample_len=elen/20, n_samples=outdim)
        # ds = Oger.datasets.mackey_glass(sample_len=elen, n_samples=1)
        ds_n = []
        for i in range(outdim):
        # for i in range(1):
            # ds1 = ds[0][0]
            # ds2 = ds[1][0]
            # rsmp = ss.resample(ds[i][0].T, elen)
            # ds_n.append(rsmp)
            f = si.interp1d(np.arange(0, elen/20), ds[i][0].T)
            tt = np.linspace(0, elen/20-1, elen)
            print f(tt)
            ds_n.append(f(tt))
            # ds_n.append(ds[i][0].T)
        # 2 rows, n cols
        # ds_real = np.vstack([ds1.T, ds2.T])
        #    print len(ds_n)
        # sys.exit()
        ds_real = np.vstack(ds_n)
        return ds_real
    elif mode == "wav":
        from scipy.io import wavfile
        # from smp.datasets import wavdataset
        # from models import SeqData
        rate, data = wavfile.read("notype_mono_short.wav")
        # rate, data = wavfile.read("drinksonus_mono_short.wav")
        offset = np.random.randint(0, data.shape[0] - elen)
        print data.dtype, offset
        data = data.astype(np.float)
        data = data[offset:offset+elen].reshape((1, -1))
        data /= np.max(np.abs(data))
        # print data.shape
        # sys.exit()
        return data
    elif mode == "reg3t1":
        f_numcomp = 1
        f_end   = (f_numcomp + 1) * f_step
        # ds = np.zeros((outdim))

    # generate waveform from frequencies array
    # d_sig_freqs_base = np.linspace(f_start, f_end, f_numcomp).reshape((1, -1))
    if mode == "reg3t1":
        # freqs = np.array([0.1, 0.21, 0.307, 0.417]) * 1e-2
        freqs = np.array([0.1]) * 1e-3
    else:
        freqs = get_frequencies(numcomp = f_numcomp)
        
    # print d_sig_freqs_base.shape
    # d_sig_freqs = np.tile(d_sig_freqs_base, (1, outdim)).T
    # print "d_sig_freqs shape = %s, data = %s" % (d_sig_freqs.shape, d_sig_freqs)
    # print (d_sig_freqs * t).shape
    # d_sig_a = np.zeros(shape=(elen, len(d_sig_freqs)))
    # for j in range(len(d_sig_freqs)):
    #     d_sig_a[:,j] = np.sin(2*np.pi*d_sig_freqs[j]*t)

    d_sig = np.zeros((outdim, elen))
    t = np.tile(t, (f_numcomp, 1))
    # print "d_sig.shape", d_sig.shape
    # print "freqs.shape", freqs.shape, t.shape
    for i in range(outdim):
        phases = np.random.uniform(0, 1, size=(f_numcomp, ))
        # freq variation for output components
        freqs += (np.random.randint(1, 3, size=(f_numcomp, )) * 0.001 * np.clip(i, 0, 1))
        # amp variation for output components
        amps = np.random.uniform(0, 1, size=(f_numcomp, ))
        # amp normalization to sum 1
        amps /= np.sum(amps)
        # compute sine waveforms from freqs, phase t and phase offset phases times amp
        sincomps = np.sin(2 * np.pi * (freqs * t.T + phases)) * amps
        # print "sincomps.shape", sincomps.shape
        d = np.sum(sincomps, axis = 1)
        # print "d.shape", d.shape
        d_sig[i] = d
    # print "d_sig.shape", d_sig.shape

    # pl.ioff()
    # pl.subplot(211)
    # pl.plot(d_sig_a)
    # pl.subplot(212)
    # pl.plot(d_sig_b.T)
    # pl.show()
            
    # d_sig = np.sum(d_sig_a, axis=1)/len(d_sig_freqs)
    # d_sig = d_sig.reshape(1, (len(d_sig)))
    return d_sig

def test_ip(args):
    idim = 1
    odim = 1
    saveplot = True
    res = Reservoir2(N=100, input_num=idim, output_num=odim, g = 0.,
                     tau = 1., feedback_scale=0., input_scale=1.0,
                     eta_init=1e-3, sparse=True, ip=True)
    # custom IP eta?
    res.ip_eta = np.ones((idim,1)) * 4e-4

    u_    = np.zeros((args.length, idim))
    for i in range(idim):
        u_[:,i]    = np.random.uniform(np.random.uniform(-5., .0),
                                       np.random.uniform(0., 5.),
                                       size=(args.length,))
        # u_[:,i]    = np.random.beta(np.random.uniform(0, 1.),
        #                                    np.random.uniform(0, 1.),
        #                                    size=(args.length,))
        # u_[:,i]    = np.random.exponential(np.random.uniform(0, 1.),
        #                                    size=(args.length,))
    u_ip_ = np.zeros((args.length, idim))
    z_    = np.zeros((args.length, odim))
    for i in range(args.length):
        # print u_[i]
        z_[i] = res.execute(u_[i])
        # print res.u
        u_ip_[i] = res.u.reshape((idim,))


    sl1 = slice(0, args.length / 3)
    sl2 = slice(args.length / 3, 2 * args.length / 3)
    sl3 = slice(2 * args.length / 3, None)
    pl.subplot(241)
    # pl.plot(u_, "k-", lw=0.3)
    pl.plot(u_ + [i * 10 for i in range(idim)], "k-", lw=0.3)
    pl.ylabel("Neuron input $x$")
    pl.subplot(242)
    pl.hist(u_[sl1], bins=50, normed=True, orientation="horizontal")
    pl.subplot(243)
    pl.hist(u_[sl2], bins=50, normed=True, orientation="horizontal")
    pl.subplot(244)
    pl.hist(u_[sl3], bins=50, normed=True, orientation="horizontal")
    pl.subplot(245)
    # pl.plot(u_ip_, "k-", lw=0.3)
    pl.plot(u_ip_, "k-", lw=0.3)
    pl.ylabel("Neuron output $y$")
    pl.subplot(246)
    pl.hist(u_ip_[sl1], bins=50, normed=True, orientation="horizontal")
    pl.subplot(247)
    pl.hist(u_ip_[sl2], bins=50, normed=True, orientation="horizontal")
    pl.subplot(248)
    pl.hist(u_ip_[sl3], bins=50, normed=True, orientation="horizontal")

    if saveplot:
        pl.gcf().set_size_inches((18,10))
        pl.gcf().savefig("reservoir_test_ip.pdf", dpi=300, bbox_inches="tight")
    pl.show()

class ReservoirTest(object):
    modes = {"ol_rls": 0, "ol_force": 1, "ol_eh": 2, "ip": 3, "fwd": 4, "ol_pi": 5, "ol_force_mdn": 6}
    targets = {"MSO_s1": 0, "MSO_s2": 1, "MSO_s3": 2, "MSO_c1": 3, "MSO_c2": 4, "MG": 5, "wav": 6, "reg3t1": 7}
    
def main(args):
    if ReservoirTest.modes[args.mode] == ReservoirTest.modes["ip"]:
        test_ip(args)
        sys.exit()

    # FIXME: define different tasks
    #  - signal generation: simple MSO, non-integer relation MSO, Mackey-Glass
    #  - compare with batch learning for signal generation
    #  - simple prediction tasks
    #  - simultaneous learning of inverse and forward model, modulate forward learning based on variance
    # FIXME:
    #  - ascii progress bar
    #  - on the fly plotting
    #  - modularize learning rules: use Reward class?

    # print args.length
    # for i in [10, 100, 1000]:
    np.random.seed(args.seed)
    # episode_len = 100000
    # episode_len = 10000
    episode_len = args.length
    washout_ratio = 0.1
    washout = washout_ratio * episode_len
    learning_ratio = args.learning_ratio
    testing = learning_ratio * episode_len
    insize = args.ndim_in
    outsize = args.ndim_out
    if args.mode == "ol_force_mdn":
        mixcomps = 3
        outsize_ = outsize * mixcomps * 3
        out_t_mdn_sample = np.zeros(shape=(outsize, episode_len))
    else:
        outsize_ = outsize
    # for feedback
    percent_factor = 1./(episode_len/100.)
    feedback_scale = args.scale_feedback
    alpha = 1.0
    input_scale = 2.0
    if args.mode.endswith("mdn"):
        alpha = 1.0 # 100.0
        input_scale = 1.0
    eta_init_ = 5e-4
    
    # get training data
    ds_real = get_data(episode_len+1, outsize, args.target)

    # compute effective tapping for these timeseries problems
    # non AR regression setup
    # mdn
    # entropy
    # loop over different hyperparams (ressize, tau, eta, ...)
    for i in [args.ressize]:
        out_t = np.zeros(shape=(outsize_, episode_len))
        out_t_n = np.zeros(shape=(outsize_, episode_len))
        r_t = np.zeros(shape=(i, episode_len))
        perf_t = np.zeros(shape=(outsize_, episode_len))
        wo_t = np.zeros(shape=(i, outsize_, episode_len))
        wo_t_norm = np.zeros((outsize_, episode_len))
        # test save and restore
        timestamp = time.strftime("%Y-%m-%d-%H%M%S")
        filename = "reservoir-%s.bin" % timestamp
        # res = Reservoir(N=10)
        # for larger reservoirs: decrease eta, increase input scale
        # res = Reservoir(N = i, input_num = insize, output_num = outsize, g = 1.5, tau = 0.01,
        #                 feedback_scale=0.1, input_scale=2.0, bias_scale=0.2, eta_init=1e-3,
        #                 theta = 1e-1, theta_state = 1e-2, coeff_a = 0.2, mtau=args.multitau)
        # tau was 0.01
        res = Reservoir(N = i, input_num = insize, output_num = outsize_, g = 1.5, tau = 0.025, alpha = alpha,
                        feedback_scale = feedback_scale, input_scale = input_scale, bias_scale=0.1, eta_init=eta_init_,
                        theta = 5e-1, theta_state = 5e-2, coeff_a = 0.2, mtau=args.multitau)
        
        # res.save(filename)
        # print ("first", res.M)
        
        # res = Reservoir2(N=i, input_num=insize, output_num=outsize, g = 1.5, tau = 0.1,
        #                 feedback_scale=0.0, input_scale=1.0, bias_scale=0.0, eta_init=1e-3,
        #                 sparse=True, coeff_a = 0.2,
        #                 ip=False, theta = 1e-5, theta_state = 1e-2)
    
        # print ("second", res.M)

        # res.load(filename)
        # print "third", res.M
        
        # print "res size", res.get_reservoir_size()
        # print "res matrix", res.get_reservoir_matrix()
        # print "res input matrix", res.get_input_matrix()
        # print "res feedback matrix", res.get_feedback_matrix()
        # print "res readout matrix", res.get_readout_matrix()

        # output weight init
        if args.mode.endswith("mdn"):
            res.init_wo_random(0, 1e-3)
        
        # learning rule module
        lr = LearningRules()

        # do some setup 
        if ReservoirTest.modes[args.mode] == ReservoirTest.modes["ol_rls"]:
            res.learnRLSsetup(None, None)
        elif ReservoirTest.modes[args.mode] == ReservoirTest.modes["ol_pi"]:
            print "ol_pi in development, not working yet"
            sys.exit(1)

        # interactive plotting
        pl.ion()
        gs = gridspec.GridSpec(5, 1)
        fig = pl.figure()
        axs = []
        for plotrow in range(5):
            axs.append(fig.add_subplot(gs[plotrow]))
        fig.show()

        # plotting params for res hidden activation random projection
        selsize = 20
        rindex = np.random.randint(i, size=selsize)

        
        # loop over timesteps        
        for j in range(episode_len):

            inputs = out_t[:,[j-1]]
            # teacher forcing
            if True or (j > testing and j < washout):
                inputs = ds_real[:,[j-1]] # .reshape((insize, 1))
            target = ds_real[:,[j]]
            
            # save network state
            res_x_ = res.x.copy()
            res_r_ = res.r.copy()
            
            # update network, log activations
            out_t[:,[j]]   = res.execute(inputs)
            out_t_n[:,[j]] = res.zn
            r_t[:,[j]] = res.r
            
            # start testing / freerunning mode
            if j < testing and j > washout:
                if ReservoirTest.modes[args.mode] == ReservoirTest.modes["ol_rls"]:
                    res.learnRLS(target)
                elif ReservoirTest.modes[args.mode] == ReservoirTest.modes["ol_force"]:
                    # reservoir class built-in learning rule
                    # res.learnFORCE(target)

                    # modular learning rule (ugly call)
                    (res.P, k, c) = lr.learnFORCE_update_P(res.P, res.r)
                    dw = lr.learnFORCE(target, res.P, k, c, res.r, res.z, 0)
                    res.wo += dw
                                    
                elif ReservoirTest.modes[args.mode] == ReservoirTest.modes["ol_force_mdn"]:
                    # reservoir class built-in learning rule
                    # res.learnFORCE(target)

                    
                    # modular learning rule (ugly call)
                    (res.P, k, c) = lr.learnFORCE_update_P(res.P, res.r)
                    dw = lr.learnFORCEmdn(target, res.P, k, c, res.r, res.z, 0, inputs)
                    res.wo += (1e-0 * dw)

                                    
                elif ReservoirTest.modes[args.mode] == ReservoirTest.modes["ol_eh"]:
                    res.eta_init = eta_init_ / (1 + ((j - washout)/20000.0))
                    res.learnEH(target)
                                        
                elif ReservoirTest.modes[args.mode] == ReservoirTest.modes["ol_pi"]:
                    if j > 100:
                        # em.x = out_t_n[:,j-1000:j].T # nlzr.X["x"][-10000:,0].reshape((10000,1))
                        # em.preprocess()
                        # em.discretize_data()
                        # res.learnPI(out_t_n[:,j-1000:j])
                        # res.perfVar(out_t_n[:,j-1000:j])
                        # res.perfVar(out_t[:,j-100:j])
                        res.perfVar(out_t)
                        # print res.perf
                        res.learnEHPerf()

                # recompute activations, only when learning
                # back up states
                res.x = res_x_
                res.r = res_r_
                # activations update with corrected ouput, and log
                out_t[:,[j]] =   res.execute(inputs)
                out_t_n[:,[j]] = res.zn
                r_t[:,[j]] = res.r

            if args.mode.endswith("mdn"):
                out_t_mdn_sample[:,[j]] = lr.mixture(res.z[:mixcomps,0], res.z[mixcomps:(2*mixcomps),0], res.z[(2*mixcomps):,0])
                # res.perf = lr.mdn_loss(target, res.z, inputs, True)
                mdn_loss_val = lr.loss
                # print "mdn_loss = %s" % mdn_loss_val
                res.perf = lr.e # mdn_loss_val
                            
            perf_t[:,[j]] = res.perf
            wo_t[:,:,j] = res.wo
            for k in range(outsize_):
                wo_t_norm[k,j] = LA.norm(wo_t[:,k,j])
            
            # print "state", res.x
            if j > washout and (j+1) % 1000 == 0:
                # # old style
                # print "eta", res.eta_init
                # print("%d of %d" % (j,  episode_len))
                # new style
                progress = j * percent_factor
                # print '\r[{0}] {1}%'.format('#'*(progress/10), progress)
                sys.stdout.write( '\r[{0}] {1}%'.format('#'*int(progress), progress))
                sys.stdout.flush()
                
                # pl.subplot(311)
                # pl.gca().clear()
                axs[0].clear()
                # backlog = 200
                backlog = 1000
                axs[0].set_title("target, %d-window" % (backlog))
                axs[0].plot(ds_real[:,(j-backlog):j].T, lw=2.0, label="tgt")
                axs[0].legend()
                axs[1].clear()
                axs[1].set_title("Target and output, %d-window" % (backlog))
                axs[1].plot(ds_real[:,(j-backlog):j].T, lw=2.0, label="tgt")
                if args.mode.endswith("mdn"):
                    axs[1].plot(out_t_mdn_sample[:,(j-backlog):j].T, lw=0.5, label="out_")
                axs[1].plot(out_t[:,(j-backlog):j].T, lw=0.5, label="out")
                axs[1].legend(ncol=2, fontsize=8)

                axs[2].clear()
                axs[2].set_title("reservoir traces")
                axs[2].plot(r_t.T[:,rindex])

                axs[3].clear()
                axs[3].set_title("weight norm |W|")
                axs[3].plot(wo_t_norm.T)
                axs[3].legend(ncol=2, fontsize=8)
                
                axs[4].clear()
                axs[4].set_title("perf (-loss)")
                axs[4].plot(perf_t.T)
                axs[4].legend(ncol=2, fontsize=8)
                
                pl.draw()
                pl.pause(1e-9)

    print "perf_t.shape", perf_t.shape

    # final plot
    pl.ioff()

    for axidx in range(5):
        axs[axidx].clear()
        
    axs[0].set_title("Target")
    axs[0].plot(ds_real.T, label="%d-dim tgt" % ds_real.shape[0])
    axs[0].legend(ncol=2, fontsize=8)

    axs[1].set_title("Target and output")
    axs[1].plot(ds_real.T, label="%d-dim tgt" % ds_real.shape[0])
    axs[1].plot(out_t.T, label="z")
    if args.mode.endswith("mdn"):
        axs[1].plot(out_t_mdn_sample.T, label = "sample z")
    axs[1].legend(ncol=2, fontsize=8)
    # axs[0].axvline(testing)
    axs[1].axvspan(testing, episode_len, alpha=0.1)
    # axs[0].plot(ds_real.T - out_t.T)

    axs[2].set_title("reservoir traces")
    axs[2].plot(r_t.T[:,rindex], label="r")

    axs[3].set_title("weight norm")
    axs[3].plot(wo_t_norm.T, label="|W|")
    axs[3].legend(ncol=2, fontsize=8)
    
    axs[4].set_title("perf (-loss)")
    axs[4].plot(perf_t[6:].T, label="perf")
    axs[4].legend(ncol=2, fontsize=8)
    
    pl.draw()
    pl.show()

    try:
        from scipy.io import wavfile
        # wav_out = (out_t.T * 32767).astype(np.int16)
        out_t /= np.max(np.abs(out_t))
        wav_out = (out_t.T * 32767).astype(np.int16)
        wavfile.write("data/res_out_%s.wav" % (time.strftime("%Y%m%d_%H%M%S")), 44100, wav_out)
    except ImportError:
        print "ImportError for scipy.io.wavfile"

if __name__ == "__main__":
    
    parser = argparse.ArgumentParser(description="Reservoir library, call main for testing: python reservoirs.py -t MSO_s1 -m ol_eh -rs 500 -l 100000")
    parser.add_argument("-l", "--length", help="Episode length [30000]", default=30000, type=int)
    parser.add_argument("-lr", "--learning_ratio", help="Ratio of learning to episode len [0.8]", default=0.8, type=float)
    parser.add_argument("-m", "--mode", help="Mode [ol_rls], one of " + str(ReservoirTest.modes.keys()), default = "ol_rls")
    parser.add_argument("-mt", "--multitau", dest="multitau", action="store_true",
                        help="use multiple random time constants in reservoir, doesn't seem to work so well with EH [False]")
    parser.add_argument("-ndo", "--ndim_out", help="Number of output dimensions [1]", default=1, type=int)
    parser.add_argument("-ndi", "--ndim_in",  help="Number of input dimensions [1]",  default=1, type=int)
    parser.add_argument("-rs", "--ressize", help="Reservoir (hidden layer) size [300]", default=300, type=int)
    parser.add_argument("-s", "--seed", help="RNG seed [101]", default=101, type=int)
    parser.add_argument("-sf", "--scale_feedback", help="Global feedback strength (auto-regressive) [0.1]", default=0.1, type=float)
    parser.add_argument("-t", "--target", help="Target [MSO_s1], one of " + str(ReservoirTest.targets.keys()), default = "MSO_s1")
    
    args = parser.parse_args()

    main(args)
