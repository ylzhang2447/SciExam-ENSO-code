"""Coupled stochastic ENSO model; dimensional observable state at the interface."""
import numpy as np
from scipy.linalg import expm


class ENSOModel:
    def __init__(self, params):
        self.scales = np.array([7.5, 7.5, 150., 1.5, 5.])[:, None]
        self.time_scale = float(params.get('time_scale_months', 2.))
        self.a = np.array([[params[f'A_{i}_{j}'] for j in range(5)] for i in range(5)])
        self.b = np.array([[params[f'B_{i}_{j}'] for j in range(5)] for i in range(5)])
        self.ac = np.array([[params.get(f'C_{i}_{j}', 0.) for j in range(5)] for i in range(5)])
        self.asin = np.array([[params.get(f'S_{i}_{j}', 0.) for j in range(5)] for i in range(5)])
        self.season2cos = np.array([params.get(f'season2cos_{i}',0.) for i in range(2)])
        self.season2sin = np.array([params.get(f'season2sin_{i}',0.) for i in range(2)])
        self.constant = np.array([params.get(f'constant_{i}', 0.) for i in range(5)])[:, None]
        self.q = np.array([params.get(f'q_{i}', 0.) for i in range(2)])[:, None]
        self.r = np.array([params.get(f'r_{i}', 0.) for i in range(2)])[:, None]
        self.m2 = np.array([params.get(f'm2_{i}', 0.) for i in range(2)])[:, None]
        self.m3 = np.array([params.get(f'm3_{i}', 0.) for i in range(2)])[:, None]
        self.wind_q = float(params.get('wind_q', 0.))
        self.recharge_q = float(params.get('recharge_q',0.))
        self.adv = np.array([params.get('adv_C',0.),params.get('adv_E',0.)])[:,None]
        self.adv_moment = np.array([params.get('moment_uC',0.),params.get('moment_uGrad',0.)])[:,None]
        self.wind_gate = float(params.get('wind_gate',0.))
        self.gate_width = float(params.get('gate_width',.1))
        self.gate_moment = float(params.get('gate_moment',0.))
        self.thermo_gain = float(params.get('thermo_gain',0.))
        self.thermo_e = float(params.get('thermo_E',0.))
        self.thermo_h = float(params.get('thermo_h',0.))
        self.thermo_offset = float(params.get('thermo_offset',0.))
        self.thermo_mean = float(params.get('thermo_mean',0.))
        self.noise_cos = np.array([[params.get(f'noise_cos{h}_{i}',0.) for i in range(5)] for h in [1,2]])
        self.noise_sin = np.array([[params.get(f'noise_sin{h}_{i}',0.) for i in range(5)] for h in [1,2]])
        self._transitions = {}

    def _nonlinear(self, x, ds, wind_heat):
        if self.wind_gate or self.thermo_gain:
            return self._nonlinear_gate(x,ds,wind_heat)
        # Implicit midpoint for the saturated local SST feedback. The cubic
        # derivative bounds the positive quadratic feedback at large amplitude.
        old = x[:2]
        y = old.copy()
        u = x[3] + ds*self.constant[3]*.5
        for _ in range(6):
            mid = (old+y)*.5
            tendency = self.constant[:2] + self.q*(mid*mid-self.m2) - self.r*(mid**3-self.m3)
            gradient = mid.copy()
            gradient[1] -= mid[0]
            tendency -= self.adv*(u*gradient-self.adv_moment)
            residual = y-old-ds*tendency
            derivative = 1-ds*(self.q*mid-1.5*self.r*mid*mid-self.adv*u*.5)
            delta = residual/derivative
            delta[1] += ds*self.adv[1]*u*.5*delta[0]/derivative[1]
            y = y-delta
        out = x + ds*self.constant
        out[:2] = y
        mid_c = (old[0]+y[0])*.5
        mid_e = (old[1]+y[1])*.5
        out[4] += ds*self.wind_q*(mid_c*mid_c-self.m2[0])
        out[2] += ds*self.recharge_q*(mid_e*mid_e-self.m2[1])
        return out

    def _nonlinear_gate(self,x,ds,wind_heat):
        # Solve C and wind first, then the coupled E/hW midpoint equation.
        u=x[3]+.5*ds*self.constant[3]
        yc=x[0].copy()
        for _ in range(6):
            m=.5*(x[0]+yc)
            f=self.constant[0]+self.q[0]*(m*m-self.m2[0])-self.r[0]*(m**3-self.m3[0])-self.adv[0]*(u*m-self.adv_moment[0])
            derivative=1-ds*(self.q[0]*m-1.5*self.r[0]*m*m-.5*self.adv[0]*u)
            yc-=(yc-x[0]-ds*f)/derivative
        mc=.5*(x[0]+yc)
        wind_tendency=self.constant[4]+self.wind_q*(mc*mc-self.m2[0])
        wind=x[4]+.5*ds*wind_tendency
        gain=wind_heat*self.wind_gate
        ye=x[1].copy()
        for _ in range(6):
            m=.5*(x[1]+ye)
            tan=np.tanh((m-mc)/self.gate_width)
            f=self.constant[1]+self.q[1]*(m*m-self.m2[1])-self.r[1]*(m**3-self.m3[1])-self.adv[1]*(u*(m-mc)-self.adv_moment[1])
            f+=gain*(wind*tan-self.gate_moment)
            derivative=1-ds*(self.q[1]*m-1.5*self.r[1]*m*m-.5*self.adv[1]*u+.5*gain*wind*(1-tan*tan)/self.gate_width)
            if self.thermo_gain:
                mh=x[2]+.5*ds*(self.constant[2]+self.recharge_q*(m*m-self.m2[1]))
                therm=np.tanh(self.thermo_offset+self.thermo_e*m+self.thermo_h*mh)
                f+=self.thermo_gain*(therm-self.thermo_mean)
                derivative-=.5*ds*self.thermo_gain*(1-therm*therm)*(self.thermo_e+self.thermo_h*ds*self.recharge_q*m)
            ye-=(ye-x[1]-ds*f)/derivative
        me=.5*(x[1]+ye)
        out=x+ds*self.constant
        out[0]=yc;out[1]=ye
        out[4]=x[4]+ds*wind_tendency
        out[2]+=ds*self.recharge_q*(me*me-self.m2[1])
        return out

    def step(self, state, dt, t, rng):
        state = np.asarray(state, dtype=float)
        if state.ndim != 2 or state.shape[0] != 5:
            raise ValueError('state must have shape (5, M)')
        if not np.isfinite(dt) or dt < 0:
            raise ValueError('dt must be finite and nonnegative')
        if dt == 0:
            return state.copy()
        if dt > .25:
            count = int(np.ceil(dt/.25))
            h = dt/count
            x = state.copy()
            for k in range(count):
                x = self.step(x,h,t+k*h,rng)
            return x
        phase = round(float((t + dt/2) % 12), 10)
        key = (dt, phase)
        if key not in self._transitions:
            ds = dt/self.time_scale
            angle = 2*np.pi*phase/12
            a = self.a + self.ac*np.cos(angle) + self.asin*np.sin(angle)
            a[np.arange(2),np.arange(2)] += self.season2cos*np.cos(2*angle)+self.season2sin*np.sin(2*angle)
            modulation = np.exp(self.noise_cos[0]*np.cos(angle)+self.noise_sin[0]*np.sin(angle)
                                +self.noise_cos[1]*np.cos(2*angle)+self.noise_sin[1]*np.sin(2*angle))
            b = self.b*modulation[:,None]
            # Van Loan exponential gives the exact finite-time noise covariance.
            aug = np.zeros((10,10))
            aug[:5,:5] = a
            aug[:5,5:] = b @ b.T
            aug[5:,5:] = -a.T
            e = expm(aug*ds)
            f = e[:5,:5]
            q = e[:5,5:] @ f.T
            w,v = np.linalg.eigh((q+q.T)/2)
            noise = v @ np.diag(np.sqrt(np.maximum(w,0.)))
            self._transitions[key] = f,noise,float(a[1,4])
        f,noise,wind_heat = self._transitions[key]
        x = self._nonlinear(state/self.scales,dt/self.time_scale/2,wind_heat)
        x = f@x + noise@rng.normal(size=x.shape)
        return self.scales*self._nonlinear(x,dt/self.time_scale/2,wind_heat)
