import numpy as np
#try:
#    import statsmodels.api as sm
#except ImportError:
#    import statsmodels as sm
import statsmodels as sm
from statsmodels.genmod.generalized_linear_model import GLM
from tqdm import tqdm
from ..utils import gislib, constants, utils
from ..core.flowdataframe import FlowDataFrame

# from geopy.distance import distance
# distfunc = (lambda p0, p1: distance(p0, p1).km)
distfunc = gislib.getDistance


def ci(i, number_locs):
    """
    The multinomial fit is a poisson fit
    with `number_locs` more parameters needed to
    implement the normalization constraints:
    i.e. the poisson variables in each of the
    `number_locs` origin location must sum to one.

    This function selects the appropriate
    parameter relative to the normalization
    constant in each origin location.
    """
    c = list(np.zeros(number_locs))
    c[i] = 1.
    return c


def exponential_deterrence_func(x, R):
    """
    Exponential deterrence function
    """
    return np.exp(- x / R)


def powerlaw_deterrence_func(x, exponent):
    """
    Power law deterrence function
    """
    return np.power(x, exponent)


def compute_distance_matrix(spatial_tessellation, origins):
    """
    Compute the matrix of distances between origin locations and all other locations.

    Parameters
    ----------
    spatial_tessellation : GeoDataFrame
        the spatial tessellation.
    
    origins : list
        indexes of the locations of origin.
    
    Returns
    -------
    distance_matrix : numpy array with distances between locations in `origins`
        and all locations in `spatial_tessellation`
    """
    coordinates = spatial_tessellation.geometry.apply(utils.get_geom_centroid, args=[True]).values

    n = len(spatial_tessellation)
    distance_matrix = np.zeros((n, n))

    for id_i in tqdm(origins):
        lat_i, lng_i = coordinates[id_i]
        for id_j in range(id_i + 1, n):
            lat_j, lng_j = coordinates[id_j]
            distance = distfunc((lat_i, lng_i), (lat_j, lng_j))
            distance_matrix[id_i, id_j] = distance
            distance_matrix[id_j, id_i] = distance
    return distance_matrix


class Gravity:
    """Gravity model.
    
    The Gravity model of human migration. In its original formulation, the probability :math:`T_{ij}` of moving from a location :math:`i` to location :math:`j` is defined as [Z1946]_:
    
    .. math::
        T_{ij} \propto \\frac{P_i P_j}{r_{ij}} 

    where :math:`P_i` and :math:`P_j` are the population of location :math:`i` and :math:`j` and :math:`r_{ij}` is the distance between :math:`i` and :math:`j`.

    Parameters
    ----------
    deterrence_func_type : str, optional
        the deterrence function to use. The possible deterrence function are "power_law" and "exponential". The default is "power_law".

    deterrence_func_args : list, optional
        the arguments of the deterrence function. The default is [-2.0].

    origin_exp : float, optional 
        the exponent of the origin's relevance (only relevant to globally-constrained model). The default is `1.0`.

    destination_exp : float, optional 
        the explonent of the destination's relevance. The default is 1.0.

    gravity_type : str, optional
        the type of gravity model. Possible values are "singly constrained" and "globally constrained". The default is "singly constrained".
        
    name : str, optional
        the name of the instantiation of the Gravity model. The default is "Gravity model".

    References
    ----------
    .. [Z1946] Zipf, G. K. (1946) The P 1 P 2/D hypothesis: on the intercity movement of persons. American sociological review 11(6), 677-686, https://www.jstor.org/stable/2087063?seq=1#metadata_info_tab_contents
    .. [W1971] Wilson, A. G. (1971) A family of spatial interaction models, and associated developments. Environment and Planning A 3(1), 1-32, https://econpapers.repec.org/article/pioenvira/v_3a3_3ay_3a1971_3ai_3a1_3ap_3a1-32.htm
    
    See Also
    --------
    Radiation
    """

    def __init__(self, deterrence_func_type='power_law', deterrence_func_args=[-2.0],
                 origin_exp=1.0, destination_exp=1.0, gravity_type='singly constrained',
                 name='Gravity model'):

        self._name = name
        self._deterrence_func_type = deterrence_func_type
        self._deterrence_func_args = deterrence_func_args
        self._origin_exp = origin_exp
        self._destination_exp = destination_exp
        self._gravity_type = gravity_type

        # set the deterrence function
        if self._deterrence_func_type == 'power_law':  # power law deterrence function
            self._deterrence_func = powerlaw_deterrence_func
        elif self._deterrence_func_type == 'exponential':  # exponential deterrence function
            self._deterrence_func = exponential_deterrence_func
        else:
            print('Deterrence function type "%s" not available. Power law will be used.\n'
                  'Available deterrence functions are [power_law, exponential]' % self._deterrence_func_type)
            self._deterrence_func = powerlaw_deterrence_func

    @property
    def name(self):
        return self._name

    @property
    def deterrence_func_type(self):
        return self._deterrence_func_type

    @property
    def deterrence_func_args(self):
        return self._deterrence_func_args

    @property
    def origin_exp(self):
        return self._origin_exp

    @property
    def destination_exp(self):
        return self._destination_exp

    @property
    def gravity_type(self):
        return self._gravity_type

    def __str__(self):
        return 'Gravity(name=\"%s\", deterrence_func_type=\"%s\", ' \
               'deterrence_func_args=%s, origin_exp=%s, destination_exp=%s, gravity_type=\"%s\")' % \
               (self._name, self._deterrence_func_type, self._deterrence_func_args, self._origin_exp,
                self._destination_exp, self._gravity_type)

    def compute_gravity_score(self, distance_matrix, relevances_orig, relevances_dest):
        trip_probs_matrix = self._deterrence_func(distance_matrix, *self._deterrence_func_args)
        # trip_probs_matrix = np.transpose(
        #     trip_probs_matrix * relevances ** self.destination_exp) * relevances ** self._origin_exp
        trip_probs_matrix = trip_probs_matrix * relevances_dest ** self.destination_exp * \
                            np.expand_dims(relevances_orig ** self._origin_exp, axis=1)
        # put the NaN and Inf to 0.0
        np.putmask(trip_probs_matrix, np.isnan(trip_probs_matrix), 0.0)
        np.putmask(trip_probs_matrix, np.isinf(trip_probs_matrix), 0.0)
        return trip_probs_matrix

    def generate(self, spatial_tessellation, tile_id_column=constants.TILE_ID,
                 tot_outflows_column=constants.TOT_OUTFLOW, relevance_column=constants.RELEVANCE, out_format='flows'):
        """
        Start the simulation of the Gravity model.
        
        Parameters
        ----------
        spatial_tessellation : GeoDataFrame
            the spatial tessellation on which to run the simulation.
            
        tile_id_column : str, optional
            the column in `spatial_tessellation` of the location identifier. The default is `constants.TILE_ID`.
            
        tot_outflows_column : str, optional
            the column in `spatial_tessellation` with the outflow of the location. The default is `constants.TOT_OUTFLOW`.
            
        relevance_column : str, optional
            the column in `spatial_tessellation` with the relevance of the location. The default is `constants.RELEVANCE`.
            
        out_format : str, optional
            the format of the generated flows. Possible values are "flows" and "probabilities". The default is "flows".
            
        Returns
        -------
        FlowDataFrame
            the flows generated by the Gravity model.
        """
        n_locs = len(spatial_tessellation)
        relevances = spatial_tessellation[relevance_column].fillna(0).values
        self._tile_id_column = tile_id_column
        # self._spatial_tessellation = spatial_tessellation

        if out_format not in ['flows', 'probabilities']:
            print('Output format \"%s\" not available. Flows will be used.\n'
                  'Available output formats are [flows, probabilities]' % out_format)
            out_format = "flows"

        if out_format == 'flows':
            if tot_outflows_column not in spatial_tessellation.columns:
                raise KeyError("The column 'tot_outflows' must be present in the tessellation.")
            tot_outflows = spatial_tessellation[tot_outflows_column].fillna(0).values

        # the origin locations are all locations
        origins = np.arange(n_locs)

        # compute the distances between all pairs of locations
        distance_matrix = compute_distance_matrix(spatial_tessellation, origins)

        # compute scores
        trip_probs_matrix = self.compute_gravity_score(distance_matrix, relevances, relevances)

        if self._gravity_type == 'globally constrained':  # globally constrained gravity model
            trip_probs_matrix /= np.sum(trip_probs_matrix)

            if out_format == 'flows':
                # generate random fluxes according to trip probabilities
                od_matrix = np.reshape(np.random.multinomial(np.sum(tot_outflows), trip_probs_matrix.flatten()),
                                       (n_locs, n_locs))
                return self._from_matrix_to_flowdf(od_matrix, origins, spatial_tessellation)
            else:
                # return trip_probs_matrix
                return self._from_matrix_to_flowdf(trip_probs_matrix, origins, spatial_tessellation)

        else:  # singly constrained gravity model
            trip_probs_matrix = np.transpose(trip_probs_matrix / np.sum(trip_probs_matrix, axis=0))

            if out_format == 'flows':
                # generate random fluxes according to trip probabilities
                od_matrix = np.array([np.random.multinomial(tot_outflows[i], trip_probs_matrix[i]) for i in origins])
                return self._from_matrix_to_flowdf(od_matrix, origins, spatial_tessellation)
            else:
                # return trip_probs_matrix
                return self._from_matrix_to_flowdf(trip_probs_matrix, origins, spatial_tessellation)

    def _from_matrix_to_flowdf(self, flow_matrix, origins, spatial_tessellation):
        index2tileid = dict([(i, tileid) for i, tileid in enumerate(spatial_tessellation[self._tile_id_column].values)])
        output_list = [[index2tileid[i], index2tileid[j], flow]
                       for i in origins for j, flow in enumerate(flow_matrix[i]) if flow > 0.]
        return FlowDataFrame(output_list, origin=0, destination=1, flow=2,
                             tile_id=self._tile_id_column, tessellation=spatial_tessellation)

    def _update_training_set(self, flow_example):

        id_origin = flow_example[constants.ORIGIN]
        id_destination = flow_example[constants.DESTINATION]
        trips = flow_example[constants.FLOW]

        if id_origin == id_destination:
            return

        try:
            coords_origin = self.lats_lngs[self.tileid2index[id_origin]]
            weight_origin = self.weights[self.tileid2index[id_origin]]
        except KeyError:
            print('Missing information for location ' + \
                  '"%s" in spatial tessellation. Skipping ...' % id_origin)
            return

        try:
            coords_destination = self.lats_lngs[self.tileid2index[id_destination]]
            weight_destination = self.weights[self.tileid2index[id_destination]]
        except KeyError:
            print('Missing information for location ' + \
                  '"%s" in spatial tessellation. Skipping ...' % id_destination)
            return

        if weight_destination <= 0:
            return

        dist = distfunc(coords_origin, coords_destination)

        if self._gravity_type == 'globally constrained':
            sc_vars = [np.log(weight_origin)]
        else:  # if singly constrained
            sc_vars = ci(self.tileid2index[id_origin], len(self.tileid2index))

        if self._deterrence_func_type == 'exponential':
            # exponential deterrence function
            self.X += [[1.] + sc_vars + [np.log(weight_destination), - dist]]
        else:
            # power law deterrence function
            self.X += [[1.] + sc_vars + [np.log(weight_destination), np.log(dist)]]

        self.y += [float(trips)]

    def fit(self, flow_df, relevance_column=constants.RELEVANCE):
        """
        Fit the parameters of the Gravity model to the flows provided in input, using a Generalized Linear Model (GLM) with a Poisson regression [FM1982]_.

        Parameters
        ----------
        flow_df  :  FlowDataFrame 
            the real flows on the spatial tessellation. 
            
        relevance_column : str, optional
            the column in the spatial tessellation with the relevance of the location. The default is constants.RELEVANCE.

        References
        ----------
        .. [FM1982] Flowerdew, R. & Murray, A. (1982) A method of fitting the gravity model based on the Poisson distribution. Journal of regional science 22(2), 191-202, https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1467-9787.1982.tb00744.x

        """
        self.lats_lngs = flow_df.tessellation.geometry.apply(utils.get_geom_centroid, args=[True]).values
        self.weights = flow_df.tessellation[relevance_column].fillna(0).values
        self.tileid2index = dict(
            [(tileid, i) for i, tileid in enumerate(flow_df.tessellation[constants.TILE_ID].values)])

        self.X, self.y = [], []  # independent (X) and dependent (y) variables

        # flow_df.progress_apply(lambda flow_example: self._update_training_set(flow_example),
        #                        axis=1)
        flow_df.apply(lambda flow_example: self._update_training_set(flow_example), axis=1)

        # Perform GLM fit
        poisson_model = GLM(self.y, self.X, family=sm.genmod.families.family.Poisson(link=sm.genmod.families.links.log))
        poisson_results = poisson_model.fit()

        # Set best fit parameters
        if self._gravity_type == 'globally constrained':
            self._origin_exp = poisson_results.params[1]
            self._destination_exp = poisson_results.params[2]
            self._deterrence_func_args = [poisson_results.params[3]]
        else:  # if singly constrained
            self._origin_exp = 1.
            self._destination_exp = poisson_results.params[-2]
            self._deterrence_func_args = [poisson_results.params[-1]]

        # we delete the instance variables we do not need anymore
        del self.X
        del self.y