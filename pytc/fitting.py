__description__ = \
"""
fitting.py

Classes for doing nonlinear regression of global models against multiple ITC
experiments.
"""
__author__ = "Michael J. Harms"
__date__ = "2016-06-22"

import copy, inspect, warnings
import numpy as np
import scipy.optimize as optimize
from matplotlib import pyplot as plt

class GlobalFit:
    """
    Class for regressing models against an arbitrary number of ITC experiments.
    """

    def __init__(self):
        """
        Set up the main binding model to fit.
        """

        # Objects for holding global parameters
        self._global_param_names = []
        self._global_fixed_param = {}
        self._global_param_guesses = {}
        self._global_param_ranges = {}
        self._global_param_mapping = {}

        # List of experiments and the weight to apply for each experiment
        self._expt_dict = {}
        self._expt_weights = {}
        self._expt_list_stable_order = []
        self._expt_fixed_param = {}

    def add_experiment(self,experiment,param_guesses=None,
                       fixed_param=None,param_aliases=None,weight=1.0):
        """
        experiment: an initialized ITCExperiment instance
        param_guesses: a dictionary of parameter guesses (need not be complete)
        fixed_param: a dictionary of parameters to be fixed, with value being
                     fixed_value.
        param_aliases: dictionary keying local experiment parameters to global
                       parameters.
        weight: how much to weight this experiment in the regression relative to other
                experiments.  Values <1.0 weight this experiment less than others;
                values >1.0 weight this more than others.
        """

        name = experiment.experiment_id

        # Record the experiment
        self._expt_dict[name] = experiment
        self._expt_list_stable_order.append(name)
        self._expt_weights[name] = weight

        if param_guesses != None:
            self._expt_dict[name].model.update_guesses(param_guesses)

        if fixed_param != None:
            self._expt_dict[name].model.update_fixed(fixed_param)

        if param_aliases != None:
            for p in param_aliases:
                self.link_to_global(-1,p,param_aliases[p])

    def remove_experiment(self,experiment):
        """
        Remove an experiment from the analysis.
        """

        expt_name = experiment.experiment_id

        # Go through all global parameters
        for k in self._global_param_mapping.keys():

            # If the experiment links to that
            for expt in self._global_param_mapping[k]:
                if expt_name == expt[0]:
                    self._global_param_mapping[k].remove(expt)

                    if len(self._global_param_mapping[k]) == 0:
                        self.remove_global(k)

        self._expt_dict.pop(expt_name)
        self._expt_list_stable_order.remove(expt_name)

    def link_to_global(self,expt,expt_param,global_param_name):
        """
        Link a local experimental fitting parameter to a global fitting
        parameter.
        """

        expt_name = expt.experiment_id

        # Make sure the experimental paramter is actually in the experiment
        if expt_param not in self._expt_dict[expt_name].model.param_names:
            err = "Parameter {} not in experiment {}\n".format(expt_param,expt_name)
            raise ValueError(err)

        # Update the alias from the experiment side
        self._expt_dict[expt_name].model.update_aliases({expt_param:
                                                         global_param_name})

        e = self._expt_dict[expt_name]
        if global_param_name not in self._global_param_names:

            # Update the alias from the global fitting side
            self._global_param_names.append(global_param_name)
            self._global_param_guesses[global_param_name] = e.model.param_guesses[expt_param]
            self._global_param_mapping[global_param_name] = [(expt_name,expt_param)]
            try:
                self._global_fixed_param[global_param_name] = e.model.fixed_param[expt_param]
            except KeyError:
                pass

            self._global_param_ranges[global_param_name] = e.model.param_ranges[expt_param]

        else:

            # Only add link between experiment and the global guess if the link is
            # not already recorded.
            if expt_name not in [m[0] for m in self._global_param_mapping[global_param_name]]:
                self._global_param_mapping[global_param_name].append((expt_name,expt_param))

    def unlink_from_global(self,expt,expt_param,global_param_name):
        """
        Remove the link between a local fitting parameter and a global
        fitting parameter.
        """

        expt_name = expt.experiment_id

        # Make sure the experimental paramter is actually in the experiment
        if expt_param not in self._expt_dict[expt_name].model.param_names:
            err = "Parameter {} not in experiment {}\n".format(expt_param,expt_name)
            raise ValueError(err)

        # Make sure global name is actually seen
        if global_param_name not in self._global_param_names:
            err = "global parameter {} not found\n".format(global_param_name)
            raise ValueError(err)

        # remove global --> expt link
        self._global_param_mapping[global_param_name].remove((expt_name,expt_param))
        if len(self._global_param_mapping[global_param_name]) == 0:
            self.remove_global(global_param_name)

        # remove expt --> global link
        self._expt_dict[expt_name].model.update_aliases({expt_param:None})


    def remove_global(self,global_param_name):
        """
        Remove a global parameter, unlinking all local parameters.
        """

        if global_param_name not in self._global_param_names:
            err = "Global parameter {} not defined.\n".format(global_param_name)
            raise ValueError(err)

        # Remove expt->global mapping from each experiment
        for k in self._global_param_mapping.keys():

            for expt in self._global_param_mapping[k]:

                expt_name = expt[0]
                expt_params = self._expt_dict[expt_name].model.param_aliases.keys()
                for p in expt_params:
                    if self._expt_dict[expt_name].model.param_aliases[p] == global_param_name:
                        self._expt_dict[expt_name].model.update_aliases({p:None})
                        break

        # Remove global data
        self._global_param_names.remove(global_param_name)
        self._global_param_guesses.pop(global_param_name)
        self._global_param_ranges.pop(global_param_name)
        self._global_param_mapping.pop(global_param_name)

        try:
            self._global_fixed_param.pop(global_param_name)
        except KeyError:
            pass


    def _residuals(self,param=None):
        """
        Calculate the residuals between the experiment and calculated model
        heats.
        """

        all_residuals = []

        for i in range(len(param)):
            param_key = self._float_param_mapping[i]
            if type(param_key) == tuple and len(param_key) == 2:
                k = param_key[0]
                p = param_key[1]
                self._expt_dict[k].model.update_values({p:param[i]})
            else:
                for k, p in self._global_param_mapping[param_key]:
                    self._expt_dict[k].model.update_values({p:param[i]})

        for k in self._expt_dict.keys():
            all_residuals.extend(self._expt_weights[k]*(self._expt_dict[k].heats - self._expt_dict[k].dQ))

        return np.array(all_residuals)


    def fit(self):
        """
        Perform a global fit using nonlinear regression.
        """

        self._float_param = []
        self._float_param_mapping = []
        float_param_counter = 0

        # Go through global variables
        for k in self._global_param_mapping.keys():
            self._float_param.append(self._global_param_guesses[k])
            self._float_param_mapping.append(k)
            float_param_counter += 1

        # Go through every experiment
        for k in self._expt_dict.keys():

            # Go through fit parameters within each experiment
            e = self._expt_dict[k]
            for p in e.model.param_names:

                # If the parameter is fixed, ignore it.
                try:
                    e.model.fixed_param[p]
                    continue
                except KeyError:
                    pass

                # If the paramter is global, ignore it.
                try:
                    e.model.param_aliases[p]
                    continue
                except KeyError:
                    pass

                # If not fixed or global, append the parameter to the list of
                # floating parameters
                self._float_param_mapping.append((k,p))
                self._float_param.append(e.model.param_guesses[p])

                float_param_counter += 1

        self._float_param = np.array(self._float_param,dtype=float)

        # Do the actual fit
        fit_param, covariance, info_dict, message, error = optimize.leastsq(self._residuals,
                                                                            x0=self._float_param,
                                                                            full_output=True)
        # Store the result
        for i in range(len(fit_param)):
            param_key = self._float_param_mapping[i]
            if len(param_key) == 2:
                k = param_key[0]
                p = param_key[1]
                self._expt_dict[k].model.update_values({p:fit_param[i]})
            else:
                for k, p in self._global_param_mapping[param_key]:
                    self._expt_dict[k].model.update_values({p:fit_param[i]})
                    self._global_param_guesses[param_key] = fit_param[i]


    def plot(self,color_list=None,correct_molar_ratio=False,subtract_dilution=False):
        """
        Plot the experimental data and fit results.
        """

        if color_list == None:
            N = len(self._expt_list_stable_order)
            color_list = [plt.cm.brg(i/N) for i in range(N)]

        if len(color_list) < len(self._expt_list_stable_order):
            err = "Number of specified colors is less than number of experiments.\n"
            raise ValueError(err)

        for i, expt_name in enumerate(self._expt_list_stable_order):

            e = self._expt_dict[expt_name]
            mr = e.mole_ratio
            heats = e.heats
            calc = e.dQ

            if e.dQ != None:

                # Try to correct molar ratio for competent fraction
                if correct_molar_ratio:
                    try:
                        mr = mr/e.param_values["fx_competent"]
                    except KeyError:
                        pass

                    if subtract_dilution:
                        heats = heats - dilution
                        calc = calc - dilution

            plt.plot(mr,heats,"o",color=color_list[i])

            if e.dQ != None:
                plt.plot(mr,calc,color=color_list[i],linewidth=1.5)

    @property
    def fit_param(self):
        """
        Return the fit results as a dictionary that keys parameter name to fit
        value.  This is a tuple with global parameters first, then a list of
        dictionaries for each local fit.
        """

        # Global parameters
        global_out_param = {}
        for g in self._global_param_names:
            global_out_param[g] = self._global_param_guesses[g]

        # Local parameters
        local_out_param = []
        for expt_name in self._expt_list_stable_order:
            local_out_param.append(self._expt_dict[expt_name].model.param_values)

        return global_out_param, local_out_param


    #--------------------------------------------------------------------------
    # parameter names

    @property
    def param_names(self):
        """
        Return parameter names. This is a tuple of global names and then a list
        of parameter names for each experiment.
        """

        final_param_names = []
        for expt_name in self._expt_list_stable_order:
            e = self._expt_dict[expt_name]

            param_names = copy.deepcopy(e.model.param_names)

            # Part of the global command names.
            for k in e.model.param_aliases.keys():
                param_names.remove(k)

            final_param_names.append(param_names)

        return self._global_param_names, final_param_names

    #--------------------------------------------------------------------------
    # parameter guesses

    @property
    def param_guesses(self):
        """
        Return parameter guesses. This is a tuple of global names and then a list
        of parameter guesses for each experiment.
        """

        final_param_guesses = []
        for expt_name in self._expt_list_stable_order:
            e = self._expt_dict[expt_name]
            param_guesses = copy.deepcopy(e.model.param_guesses)

            for k in e.model.param_aliases.keys():
                param_guesses.pop(k)

            final_param_guesses.append(param_guesses)

        return self._global_param_guesses, final_param_guesses

    def update_guess(self,param_name,param_guess,expt=None):
        """
        Update the one of the guesses for this fit.  If the experiment is None,
        set a global parameter.  Otherwise, set the specified experiment.

            param_name: name of parameter to set
            param_guess: value to set parameter to
            expt_name: name of experiment
        """

        if expt == None:
            self._global_param_guesses[param_name] = param_guess
        else:
            self._expt_dict[expt.experiment_id].model.update_guesses({param_name:param_guess})

    #--------------------------------------------------------------------------
    # parameter ranges

    @property
    def param_ranges(self):
        """
        Return the parameter ranges for each fit parameter. This is a tuple.
        Global parameters are first, a list of local parameter ranges are next.
        """

        final_param_ranges = []
        for expt_name in self._expt_list_stable_order:
            e = self._expt_dict[expt_name]
            param_ranges = copy.deepcopy(e.model.param_ranges)

            for k in e.model.param_aliases.keys():
                param_ranges.pop(k)

            final_param_ranges.append(param_ranges)

        return self._global_param_ranges, final_param_ranges

    def update_range(self,param_name,param_range,expt=None):
        """
        Update the range of a parameter for this fit.  If the experiment is None,
        set a global parameter.  Otherwise, set the specified experiment.

            param_name: name of parameter to set
            param_guess: value to set parameter to
            expt_name: name of experiment
        """

        try:
            if len(param_range) != 2:
                raise TypeError
        except TypeError:
            err = "Parameter range must be a list or tuple of length 2"
            raise TypeError(err)

        if expt == None:
            self._global_param_ranges[param_name] = param_range
        else:
            self._expt_dict[expt.experiment_id].model.update_ranges({param_name:param_range})

    #--------------------------------------------------------------------------
    # fixed parameters

    @property
    def fixed_param(self):
        """
        Return the fixed parameters of the fit.  This is a tuple,  Global fixed
        parameters are first, a list of local fixed parameters is next.
        """

        final_fixed_param = []
        for expt_name in self._expt_list_stable_order:

            e = self._expt_dict[expt_name]

            fixed_param = copy.deepcopy(e.model.fixed_param)

            for k in e.model.param_aliases.keys():
                try:
                    fixed_param.pop(k)
                except KeyError:
                    pass

            final_fixed_param.append(fixed_param)

        return self._global_fixed_param, final_fixed_param

    def fix(self,expt=None,**kwargs):
        """
        Fix fit parameters.  If expt is None, set a global parameter. Otherwise,
        fix individual experiment parameters.  kwargs takes individual fit
        parameter names and values.
            param_name: name of parameter to set
            param_guess: value to set parameter to
            expt_name: name of experiment

        """

        if expt == None:
            for k in kwargs.keys():
                self._global_fixed_param[k] = kwargs[k]
        else:
            self._expt_dict[expt.experiment_id].model.update_fixed(kwargs)

    def unfix(self,*args,expt=None):

        if expt == None:
            for a in args:
                try:
                    self._global_fixed_param.pop(a)
                except KeyError:
                    pass
        else:
            for a in args:
                self._expt_dict[expt.experiment_id].model.update_fixed({a:None})


    #--------------------------------------------------------------------------
    # parameter aliases

    @property
    def param_aliases(self):
        """
        Return the parameter aliases.  This is a tuple.  The first entry is a
        dictionary of gloal parameters mapping to experiment number; the second
        is a map between experiment number and global parameter names.
        """

        expt_to_global = []
        for expt_name in self._expt_list_stable_order:
            e = self._expt_dict[expt_name]
            expt_to_global.append(copy.deepcopy(e.model.param_aliases))


        return self._global_param_mapping, expt_to_global

    @property
    def experiments(self):
        """
        Return a list of associated experiments.
        """

        out = []
        for expt_name in self._expt_list_stable_order:
            out.append(self._expt_dict[expt_name])

        return out
