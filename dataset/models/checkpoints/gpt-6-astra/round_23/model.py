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
        self.thermo_c = float(params.get('thermo_C',0.))
        self.thermo_tau = float(params.get('thermo_tau',0.))
        self.thermo_offset = float(params.get('thermo_offset',0.))
        self.thermo_mean = float(params.get('thermo_mean',0.))
        self.thermo_season = np.array([params.get('thermo_cos',0.),params.get('thermo_sin',0.)])
        self.noise_state = np.array([params.get('noise_state_C',0.),params.get('noise_state_E',0.)])
        self.noise_heat = np.array([params.get('noise_heat_C',0.),params.get('noise_heat_E',0.),params.get('noise_heat_h',0.)])
        self.wind_asym = float(params.get('wind_asym',0.))
        self.wind_width = float(params.get('wind_asym_width',.4))
        self.wind_moment = float(params.get('wind_asym_moment',0.))
        self.wind_heat_gate = float(params.get('wind_heat_gate',0.))
        self.wind_heat_width = float(params.get('wind_heat_width',.1))
        self.wind_heat_moment = float(params.get('wind_heat_moment',0.))
        self.heat_asym = float(params.get('heat_asym',0.))
        self.heat_width = float(params.get('heat_asym_width',.1))
        self.heat_moment = float(params.get('heat_asym_moment',0.))
        self.noise_cos = np.array([[params.get(f'noise_cos{h}_{i}',0.) for i in range(5)] for h in [1,2]])
        self.noise_sin = np.array([[params.get(f'noise_sin{h}_{i}',0.) for i in range(5)] for h in [1,2]])
        self._transitions = {}

    def _heat_asym_step(self,x,ds,rate):
        if not self.heat_asym:return x
        old=x[2];y=old.copy()
        gain=rate*self.heat_asym
        for _ in range(6):
            z=.5*(old+y)/self.heat_width
            f=gain*self.heat_width*(np.logaddexp(z,-z)-np.log(2.)-self.heat_moment)
            derivative=1-.5*ds*gain*np.tanh(z)
            y-=(y-old-ds*f)/derivative
        out=x.copy();out[2]=y
        return out

    def _nonlinear(self, x, ds, wind_heat, thermo_heat=1., wind_relax=0., wind_sst=0., heat_relax=0.):
        if not self.wind_heat_gate and not self.heat_asym:
            return self._nonlinear_base(x,ds,wind_heat,thermo_heat,wind_relax)
        # Symmetric composition with the exact heat-dependent wind translation.
        gain=.5*ds*wind_sst*self.wind_heat_gate
        x=self._heat_asym_step(x.copy(),.5*ds,heat_relax)
        x[4]+=gain*(x[0]*np.tanh(x[2]/self.wind_heat_width)-self.wind_heat_moment)
        out=self._nonlinear_base(x,ds,wind_heat,thermo_heat,wind_relax)
        out[4]+=gain*(out[0]*np.tanh(out[2]/self.wind_heat_width)-self.wind_heat_moment)
        return self._heat_asym_step(out,.5*ds,heat_relax)

    def _nonlinear_base(self, x, ds, wind_heat, thermo_heat, wind_relax):
        if self.wind_gate or self.thermo_gain or self.wind_asym:
            return self._nonlinear_gate(x,ds,wind_heat,thermo_heat,wind_relax)
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

    def _nonlinear_gate(self,x,ds,wind_heat,thermo_heat,wind_relax):
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
        if self.wind_asym:
            yw=x[4]+ds*wind_tendency
            for _ in range(6):
                mw=.5*(x[4]+yw)
                z=mw/self.wind_width
                logcosh=np.logaddexp(z,-z)-np.log(2.)
                fw=wind_tendency+wind_relax*self.wind_asym*self.wind_width*(logcosh-self.wind_moment)
                derivative=1-.5*ds*wind_relax*self.wind_asym*np.tanh(z)
                yw-=(yw-x[4]-ds*fw)/derivative
            wind=.5*(x[4]+yw)
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
                therm=np.tanh(self.thermo_offset+self.thermo_e*m+self.thermo_h*mh+self.thermo_c*mc+self.thermo_tau*wind)
                f+=self.thermo_gain*thermo_heat*(therm-self.thermo_mean)
                derivative-=.5*ds*self.thermo_gain*thermo_heat*(1-therm*therm)*(self.thermo_e+self.thermo_h*ds*self.recharge_q*m)
            ye-=(ye-x[1]-ds*f)/derivative
        me=.5*(x[1]+ye)
        out=x+ds*self.constant
        out[0]=yc;out[1]=ye
        out[4]=2*wind-x[4]
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
            # Symmetric square roots give the same Gaussian covariance while
            # varying continuously as calibrated drift coefficients change.
            noise = (v*np.sqrt(np.maximum(w,0.)))@v.T
            components=[]
            remainder=q.copy()
            for column,response in [(4,self.noise_state),(2,self.noise_heat)]:
                if not np.any(response):continue
                # Independent Cholesky channels keep covariance positive for any
                # bounded state-dependent activity. Channel 2 is shared ocean
                # heat/current/weather forcing; channel 4 forces wind alone.
                aug[:5,5:]=np.outer(b[:,column],b[:,column])
                ec=expm(aug*ds)
                qc=ec[:5,5:]@f.T
                w,v=np.linalg.eigh((qc+qc.T)/2)
                factor=(v*np.sqrt(np.maximum(w,0.)))@v.T
                components.append((response,factor))
                remainder-=qc
            if components:
                w,v=np.linalg.eigh((remainder+remainder.T)/2)
                noise=(v*np.sqrt(np.maximum(w,0.)))@v.T
            thermo_heat=np.exp(self.thermo_season[0]*np.cos(angle)+self.thermo_season[1]*np.sin(angle))
            self._transitions[key] = f,noise,float(a[1,4]),thermo_heat,components,float(a[4,4]),float(a[4,0]),float(a[2,2])
        f,noise,wind_heat,thermo_heat,components,wind_relax,wind_sst,heat_relax = self._transitions[key]
        x = self._nonlinear(state/self.scales,dt/self.time_scale/2,wind_heat,thermo_heat,wind_relax,wind_sst,heat_relax)
        # All activities are frozen before any random increment (Ito).
        activities=[np.exp(np.tanh(response@x[:len(response)]))for response,factor in components]
        y=f@x+noise@rng.normal(size=x.shape)
        for activity,(_,factor) in zip(activities,components):
            y+=activity*(factor@rng.normal(size=x.shape))
        x=y
        return self.scales*self._nonlinear(x,dt/self.time_scale/2,wind_heat,thermo_heat,wind_relax,wind_sst,heat_relax)
