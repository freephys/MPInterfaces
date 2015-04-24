from __future__ import division, unicode_literals, print_function

"""
Defines the Interface(extends class Slab) and
Ligand(extends class Molecule) classes
"""

import sys
import math
import logging

import numpy as np

from pymatgen.core.structure import Structure, Molecule
from pymatgen.core.lattice import Lattice
from pymatgen.core.surface import Slab, SlabGenerator
from pymatgen.core.operations import SymmOp
from pymatgen.util.coord_utils import get_angle

from mpinterfaces.transformations import reduced_supercell_vectors
from mpinterfaces.utils import get_ase_slab

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(levelname)s:%(name)s:%(message)s')
sh = logging.StreamHandler(stream=sys.stdout)
sh.setFormatter(formatter)
logger.addHandler(sh)


class Interface(Slab):
    """
    Interface = slab + ligand + environment(solvent)
    
    """
    def __init__(self, strt, hkl=[1,1,1], min_thick=10, min_vac=10,
                 supercell=[1,1,1], name=None, adsorb_on_species=None,
                 adatom_on_lig=None, ligand=None, displacement=1.0,
                 surface_coverage=None, scell_nmax=10, coverage_tol=0.25,
                 solvent=None, start_from_slab=False, validate_proximity=False,
                 to_unit_cell=False, coords_are_cartesian=False, primitive = True,
                 from_ase=False):
        """
        if starting from the bulk structure, create slab
        note: if the starting structure is a slab, the vaccum extension
        is not possible
        """
        self.from_ase = from_ase
        vac_extension = 0
        if ligand is not None:
            vac_extension = ligand.max_dist

        if isinstance(strt, Structure) and not isinstance(strt, Slab):
            self.min_vac = min_vac + vac_extension
            if self.from_ase:
                strt = get_ase_slab(strt, hkl=hkl,min_thick=min_thick,
                                    min_vac=min_vac + vac_extension)
            else:
                strt = SlabGenerator(strt, hkl, min_thick, min_vac + vac_extension,
                                    center_slab=True, primitive = primitive).get_slab()
            strt.make_supercell(supercell)
        else:
            self.min_vac = min_vac
        Slab.__init__(self, strt.lattice, strt.species_and_occu,
                           strt.frac_coords, miller_index=strt.miller_index,
                           oriented_unit_cell=strt.oriented_unit_cell,
                           shift=strt.shift, scale_factor=strt.scale_factor,
                           validate_proximity=validate_proximity,
                           to_unit_cell=to_unit_cell,
                           coords_are_cartesian=coords_are_cartesian,
                           site_properties=strt.site_properties,
                           energy=strt.energy )
        self.name = name
        self.hkl = hkl
        self.min_thick = min_thick
        self.supercell = supercell
        self.ligand = ligand
        self.slab = strt
        self.displacement = displacement
        self.solvent = solvent
        self.surface_coverage = surface_coverage
        self.adsorb_on_species = adsorb_on_species
        self.adatom_on_lig = adatom_on_lig
        self.scell_nmax = scell_nmax
        self.coverage_tol = coverage_tol

    def set_top_atoms(self):
        """
        set the list of top and bottom atoms indices
        """
        n_atoms = len(self.frac_coords[:,0])
        a, b, c = self.oriented_unit_cell.lattice.matrix
        h = abs(np.dot(self.normal, c))
        nlayers_slab = int(math.ceil(self.min_thick / h))
        nlayers_vac = int(math.ceil(self.min_vac / h))
        nlayers = nlayers_slab + nlayers_vac
        self.top_atoms = []
        self.bottom_atoms = []            
        for i in range(n_atoms):
            if np.abs(self.frac_coords[i][2] - max(self.frac_coords[:,2])) < 1e-6:
                if  self[i].species_string == self.adsorb_on_species:
                    self.top_atoms.append(i)
            elif np.abs(self.frac_coords[i][2] - min(self.frac_coords[:,2])) < 1e-6:
                self.bottom_atoms.append(i)

    def enforce_coverage(self):
        """
        adjusts the supercell size and the number of adsorbed ligands
        so as to meet the surface coverage criterion within the given
        tolerance limit(specified as fraction of the required
        surface coverage)
        
        returns the number of ligands  and the supercell size  that
        satisfies the criterion
        """
        n_atoms = len(self.frac_coords[:,0])
        self.top_bot_dist = np.max(self.distance_matrix.reshape(n_atoms*n_atoms, 1))
        self.set_top_atoms()        
        n_top_atoms =  len(self.top_atoms)
        max_coverage = n_top_atoms/self.surface_area
        m = self.lattice.matrix
        surface_area = np.linalg.norm(np.cross(m[0], m[1]))        
        logger.info('\nrequested surface coverage = {}'.format(self.surface_coverage))
        logger.info('maximum possible coverage = {}'.format(max_coverage))
        if self.surface_coverage:
            if self.surface_coverage > max_coverage:
                logger.info('requested surface coverage exceeds the max possible coverage')
            else:
                for scell in range(1, self.scell_nmax):
                    for nlig in range(1, scell*n_top_atoms+1):
                        surface_area = scell * surface_area
                        surface_coverage = nlig/surface_area
                        diff_coverage = np.abs(surface_coverage - self.surface_coverage)
                        if diff_coverage<=self.surface_coverage*self.coverage_tol:
                            logger.info('\ntolerance limit = {}'
                                        .format(self.coverage_tol))                                
                            logger.info('\npossible coverage within the tolerance limit = {}'
                                        .format(nlig/surface_area))
                            logger.info('supercell size = {}'.format(scell))
                            logger.info('number of ligands = {}'.format(nlig))
                            return scell, nlig

    def get_reduced_scell(self):
        """
        enforces the surface coverage criterion and generates
        the list all reduced lattice vectors that correspond to
        the computed supercell size and returns the one with similar
        lattice vector norms
        """
        scell, nlig = self.enforce_coverage()
        ab = [self.lattice.matrix[0,:], self.lattice.matrix[1,:]]
        uv_list = reduced_supercell_vectors(ab, scell)
        logger.info('\nlist of possible reduced lattice vectors {}'
                    .format(uv_list))
        norm_list = []
        for  uv in uv_list:
            unorm = np.linalg.norm(uv[0])
            vnorm = np.linalg.norm(uv[1])
            norm_list.append(abs(1. - unorm/vnorm))
        return nlig, uv_list[np.argmin(norm_list)]

    def cover_surface(self, site_indices):
        """
        puts the ligand molecule on the given list of site indices
        """
        num_atoms = len(self.ligand)
        normal = self.normal
        # get a vector that points from one atom in the botton plane
        # to one atom on the top plane. This is required to make sure
        # that the surface normal points outwards from the surface on
        #  to which we want to adsorb the ligand
        vec_vac = self.cart_coords[self.top_atoms[0]] - \
          self.cart_coords[self.bottom_atoms[0]]
        # mov_vec = the vector along which the ligand will be displaced
        mov_vec = normal * self.displacement
        angle = get_angle(vec_vac, self.normal)
        # flip the orientation of normal if it is not pointing in
        # the right direction.
        if ( angle > 90 ):
            normal_frac =  self.lattice.get_fractional_coords(normal)
            normal_frac[2] = -normal_frac[2]
            normal = self.lattice.get_cartesian_coords(normal_frac)
            mov_vec = normal * self.displacement
        # get the index corresponding to the given atomic species in
        # the ligand that will bond with the surface on which the
        # ligand will be adsorbed
        adatom_index = self.get_index(self.adatom_on_lig)
        adsorbed_ligands_coords = []
        # set the ligand coordinates for each adsorption site on the surface
        for sindex in site_indices:
            # align the ligand wrt the site on the surface to which
            # it will be adsorbed
            origin = self.cart_coords[sindex]
            self.ligand.translate_sites(list(range(num_atoms)),
                                        origin - self.ligand[adatom_index].coords )
            # displace the ligand by the given amount in the direction
            # normal to surface
            self.ligand.translate_sites(list(range(num_atoms)), mov_vec)
            # vector pointing from the adatom_on_log to the
            # ligand center of mass
            vec_adatom_cm = self.ligand.center_of_mass - \
              self.ligand[adatom_index].coords
            # rotate the ligand with respect to a vector that is
            # normal to the vec_adatom_cm and the normal to the surface
            # so that the ligand center of mass is aligned along the
            # outward normal to the surface
            origin = self.ligand[adatom_index].coords 
            angle = get_angle(vec_adatom_cm, normal)
            if 1 < abs(angle % 180) < 179:
                # For angles which are not 0 or 180,
                # perform a rotation about the origin along an axis
                # perpendicular to both bonds to align bonds.
                axis = np.cross(vec_adatom_cm, normal)
                op = SymmOp.from_origin_axis_angle(origin, axis, angle)
                self.ligand.apply_operation(op)
            elif abs(abs(angle) - 180) < 1:
                # We have a 180 degree angle.
                # Simply do an inversion about the origin
                for i in range(len(self.ligand)):
                        self.ligand[i] = (self.ligand[i].species_and_occu,
                                       origin - (self.ligand[i].coords - origin))
            adsorbed_ligands_coords.append(self.ligand.cart_coords) #3d numpy array
        #extend the slab structure with the adsorbant atoms
        adsorbed_ligands_coords = np.array(adsorbed_ligands_coords)
        for j in range(len(site_indices)):
            [self.append(self.ligand.species_and_occu[i],
                         adsorbed_ligands_coords[j,i,:], coords_are_cartesian=True)
            for i in range(num_atoms)]
        
    def get_index(self, species_string):
        """
        get the first site index of the atomic species
        """
        for i in range(len(self.ligand)):
             if self.ligand[i].species_string == species_string:
                 return i

                        
    def create_interface(self):
        """
        creates the interface i.e creates a slab of given thicknes and
        vacuum space. It ensures that the cell is big enough and
        have enough ligands to satify the surface coverage criterion
        also sets the slab on which the ligand is adsorbed
        """
        if self.ligand is not None:
            nlig, uv = self.get_reduced_scell()
            self.n_ligands = nlig        
            logger.info(
                '\nusing ... {0} ligands on a supercell with in-plane lattice vectors {1}'
                .format(self.n_ligands, uv))
            new_latt_matrix = [ uv[0][:], uv[1][:], self.lattice.matrix[2,:]]
            new_latt = Lattice(new_latt_matrix)
            _, __, scell = self.lattice.find_mapping(new_latt) #ltol = 0.01, atol=1)
            #self.scell = self.possible_scells[opt_lig_scell_index]
            self.make_supercell(scell)
            self.set_slab()
            self.set_top_atoms()
            self.adsorb_sites = [ self.top_atoms[i]
                                  for i in range(self.n_ligands)]
            logger.info('ligands will be adsorbed on these sites on the slab {}'.format(self.adsorb_sites))
            self.cover_surface(self.adsorb_sites)
            #        else:
            #            logger.critical('none of the combinations of number of ligands')
            #            logger.critical(' and supercell sizes matches the requested surface coverage')
            #            logger.critical('try increasing the tolerance or ')
            #            logger.critical('increase the maximum number of cells in the supercell')
            #            sys.exit()
        else:
            logger.info('no ligands. just the bare slab')
            

    def set_slab(self):
        """ set the slab on to which the ligand is adsorbed"""
        self.slab = Slab.from_dict(self.as_dict())
        
    def to_dict(self):
        d = self.as_dict()
        d['hkl'] = list(self.miller_index)
        d['ligand'] = None
        if self.ligand is not None:
            d['ligand'] = self.ligand.to_dict()
        if d['ligand'] is not None:
            d['num_ligands'] = self.n_ligands
        else:
            d['num_ligands'] = 0            
        return d
    
    def copy(self):
        return Structure.from_sites(self)

            
class Ligand(Molecule):
    """
    Construct ligand from  molecules
    """
    def __init__(self, mols, cm_dist=[], angle={}, link={}, remove=[],
                 charge=0, spin_multiplicity=None,
                 validate_proximity=False):
        Molecule.__init__(self, mols[0].species_and_occu, mols[0].cart_coords,
                          charge=charge, spin_multiplicity=spin_multiplicity,
                          validate_proximity=validate_proximity,
                          site_properties=mols[0].site_properties)
        self._sites = list(self._sites)
        self.mols = mols
        self.cm_dist = cm_dist
        self.angle = angle
        self.link = link
        self.remove = remove
        if len(self.mols)==1:
            self.set_distance_matrix(self.mols[0])

    def get_perp_vec(self, vec1, vec2):
        """
        returns the vector that is perpendicular to the vec1 and vec2
        if the vectors are parllel, then perp_vec = (0, -z, y)        
        """
        if np.abs(np.dot(vec1, vec2) - np.linalg.norm(vec1)**2 ) < 1e-6:
            perp_vec = np.array([0, -vec1[2], vec1[1]])
        else:
            perp_vec = np.cross(vec1, vec2)
        return perp_vec                        
    
    def set_distance_matrix(self, mol):
        """
        sets the distance matrix for the molecule
        """
        nsites = len(mol.sites)
        self.d_mat =  np.array([mol.get_distance(i,j) for i in range(nsites) \
                         for j in range(nsites)]).reshape(nsites, nsites)
        self.max_dist = np.max(self.d_mat.reshape(nsites*nsites, 1))

    def set_mol_vecs(self):
        """
        get the start and end indices to define the vector that
        defines the molecule
        sets the vectors that point from the start index atom to
        the farthest atom for each molecule
        """
        self.vec_indices = []
        for mol in self.mols:
            nsites = len(mol.sites)
            self.set_distance_matrix(mol)
            temp = []
            for i in range(nsites):
                if i not in temp:
                    [temp.append([i,j]) for j in range(nsites) \
                     if np.abs(self.max_dist-self.d_mat[i,j]) < 1e-6]
            self.vec_indices.append(temp[0])
        self.mol_vecs = []
        for mol,vind in enumerate(self.vec_indices):
            self.mol_vecs.append(self.mols[mol].cart_coords[vind[1]] - \
                                 self.mols[mol].cart_coords[vind[0]])

    def position_mols(self):
        """
        position the center of masses of the molecules wrt each other
        first movement is in the x direction        
        """
        new_mol = self.mols[0]
        mov_vec = np.array([1,0,0])
        for i in range(len(self.mols)-1):
            #cm1 = new_mol.center_of_mass
            new_cm = new_mol.center_of_mass        
            #cm2 = self.mols[i+1].center_of_mass
            new_cm = new_cm + self.cm_dist[i] * mov_vec #+ np.random.rand(1,3)
            mov_vec = self.get_perp_vec(self.mol_vecs[i], mov_vec)
            mov_vec = mov_vec / np.linalg.norm(mov_vec)
            new_coords = self.mols[i+1].cart_coords + new_cm
            self.mols[i+1] = Molecule(self.mols[i+1].species_and_occu, new_coords,
                          charge=self.mols[i+1]._charge,
                          spin_multiplicity=self.mols[i+1]._spin_multiplicity,
                          site_properties=self.mols[i+1].site_properties)
            new_mol = Molecule.from_sites(self.mols[i].sites + self.mols[i+1].sites,
                                           validate_proximity=True)

    def rotate_mols(self):
        """
        rotate the molecules wrt each other using the provided info
        """
        #rotate the molecules around an axis that is
        #perpendicular to the molecular axes
        if self.angle:
            for mol in range(len(self.mols)):
                for ind_key, rot in self.angle[str(mol)].items():
                    #print 'mol, ind_key, rot ', mol, ind_key, rot
                    perp_vec = np.cross(self.mol_vecs[int(ind_key)],
                                         self.mol_vecs[mol])
                    #if the vectors are parllel, then perp_vec = (-y, x, 0)
                    if np.abs( np.dot( self.mol_vecs[int(ind_key)],
                                      self.mol_vecs[mol] ) - \
                                      np.linalg.norm(self.mol_vecs[mol])**2 ) < 1e-6:
                        perp_vec = np.array([-self.mol_vecs[mol][1],
                                             self.mol_vecs[mol][0], 0])
                        org_pt = self.vec_indices[mol][0]
                        op = SymmOp.from_origin_axis_angle(
                            self.mols[mol].cart_coords[org_pt],
                            axis=perp_vec, angle=rot )
                        self.mols[mol].apply_operation(op)

    def link_mols(self):
        """
        link the molecules together
        connect the specified atoms of mol to the atoms of other
        molecules in the list
        connection means putting the atomm  of the mol at
        a position that is the average of the position of
        the atoms of the molecules given in the list
        """
        new_coords = np.array([0,0,0]) 
        displacement = np.array([0,0,0])
        if self.link:
            for mol in range(len(self.mols)):
                new_coords = copy.deepcopy(self.mols[mol].cart_coords)
                if link[str(mol)]:
                    for ind_key, conn in self.link[str(mol)].items():
                        ind = int(ind_key)
                        logger.info('connection list for atom of index {0} of molecule {1} : {2}'.format(ind, mol, conn))
                        coord = np.array([0,0,0])
                        #if connecting the molecule mol to only one atom of
                        #just one another molecule
                        #then move the atom close to the atom in mol and
                        #shift the whole molecule 
                        non_neg = np.extract(np.array(conn)>0, conn)
                        if len(non_neg) == 1 and len(link[str(mol)]) == 1:
                            for j,k in enumerate(conn):
                                coord = self.mols[j].cart_coords[non_neg[0]] + \
                                      np.random.rand(1,3) + 1.0
                            displacement = coord - self.mols[mol].cart_coords[ind]
                        else:
                            for j,k in enumerate(conn):
                                if k>=0:
                                    coord = coord + self.mols[j].cart_coords[k] 
                            coord = coord / len(conn)
                        new_coords[ind, 0] = coord[0]
                        new_coords[ind, 1] = coord[1]
                        new_coords[ind, 2] = coord[2]
                    new_coords = new_coords + displacement
                    self.mols[mol] =  Molecule(self.mols[mol].species_and_occu,
                                               new_coords, charge = \
                                               self.mols[mol]._charge,
                                               spin_multiplicity = \
                                               self.mols[mol]._spin_multiplicity,
                                               site_properties = \
                                               self.mols[mol].site_properties)

    def create_ligand(self):
        """
        create the ligand by assembling the provided individual molecules
        and removeing the specified atoms from the molecules
        """
        self.set_mol_vecs()
        self.position_mols()
        self.rotate_mols()
        self.link_mols()        
        for i in range(len(self.mols)):
            if self.remove[i]:
                self.mols[i].remove_sites(self.remove[i])
        combine_mol_sites = self.mols[0].sites
        for j in range(1, len(self.mols)):
            combine_mol_sites = combine_mol_sites + self.mols[j].sites
        self._sites = combine_mol_sites
        self.set_distance_matrix(self)
        
    def to_dict(self) :
        d = self.as_dict()
        d['name'] = self.composition.formula
        return d

    def copy(self):
        return Structure.from_sites(self)

#test
if __name__=='__main__':
    from pymatgen.io.vaspio.vasp_input import Poscar    
    ########################################
    #create lead acetate ligand
    #from 3 molecules: 2 acetic acid + 1 Pb
    ########################################
    mol0 = Molecule.from_file("acetic_acid.xyz")
    mol1 = Molecule.from_file("acetic_acid.xyz")
    mol2 = Molecule(["Pb"], [[0,0,0]])
    mols = [mol0, mol1, mol2]

    #center of mass distances in angstrom
    #example: 3 molecules and cm_dist = [4,2],
    #center of mass of mol1 is moved from mol0 in 1,0,0 direction by 4 A
    #mol2 is moved from the center of mass of the combined mol0+mol1 molecule by 2 A
    # in a direction that is perpendicular to the first moving direction and the
    #molecule vector of one of the molecules
    # for n molecules the size of cm_dist must be n-1
    cm_dist = [1, 2]

    #optional parmater
    #example: angle={'0':{}, '1':{'0':90}, '2':{} }
    #rotate mol1 with respect to mol0 by 90 degreeen around and axis that is normal
    # to the plane containing the molecule vectors of mol0 and mol1
    angle={'0':{}, '1':{'0':90}, '2':{} }
    
    #optional paramter
    #a dictionary describing the connection between the molecules, used if the
    #relative movemnet of the molecules throught the center of mass shift is not enough
    #the key is the index for the molecules
    #the value for each key is a list of lists wiht each list
    #indicating how the atom of index
    # corresponding to the list index in the molecule
    #coresponding to key  should be connectd to the atoms
    #in the list
    #if not connecting to any atom of the molecule set that index for that molecule to -1
    #example:- link = {'0':{}, '1':{}, '2':{'0':[6,2, -1]} }
    #the 0th atom of the third molecule,'2', is connected to the 6th
    #and 2nd atoms of molecules
    #'0' and '1' respectively and no coonection to the molecule'2' (indicated by -1)
    #if not connecting a single atom of one molecule to another atom
    #of one another molecule, connection basically means
    # putting the atom at a halfway distance between other atoms
    link = {'0':{}, '1':{}, '2':{'0':[6,2, -1]} }
        
    #list of indices of atoms to be removed from each molecule
    remove = [[7],[7],[]]
    
    #combined_mol = combine_mols(mols, cm_dist, angle, link=link, remove=remove)
    lead_acetate = Ligand(mols, cm_dist, angle=angle, link={}, remove=remove)
    lead_acetate.create_ligand()
    lead_acetate.to('xyz', 'lead_acetate.xyz')

    #put the ligand in a box
    boxed_lead_acetate = lead_acetate.get_boxed_structure(13, 13, 13)  
    boxed_lead_acetate.to(fmt= "poscar", filename= "POSCAR_diacetate_boxed.vasp")

    ########################################
    # H2O ligand
    ########################################        
    # PBEPBE/aug-cc-pVQZ , from cccbdb
    #0 0 0.119079
    #0 0.7648 -0.476318
    #0 -0.7648 -0.476318
    #adsorb species 'O' on atom of index 3 shifted by 1.0 A
    #slb.add_adsorbate_atom([3], 'O', 1.0)
    adatoms = ['O','H', 'H']
    adatoms_coords = np.array([ [0,0,0], [0, 0.77, 0.60], [0, -0.77, 0.60]])
    mol = Molecule(adatoms, adatoms_coords)
    h2o = Ligand([mol])

    ########################################
    # Interface = Slab + ligand + solvent(to do)
    # Cu surface with H2O as ligands
    #######################################

    a0 = 3.62 #from materials project
    latt = Lattice.cubic(a0)
    species = ["Cu", "Cu", "Cu", "Cu"]
    positions = [[0, 0, 0], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]]
    
    #initial structure, must be either a bulk structure or a slab
    strt_cu = Structure(latt, species, positions)

    strt_pbs = Structure.from_file('POSCAR.mp-21276_PbS')
    
    #intital supercell, this wont be the final supercell if surface coverage is specified
    supercell = [1,1,1]

    #miller index
    hkl = [1,0,0]
    
    #minimum slab thickness in Angstroms
    min_thick = 21
    
    #minimum vacuum thickness in Angstroms
    #the maximum distance in the lignad will be added to this value
    min_vac = 10
    
    # surface coverage in the units of lig/ang^2
    #mind: exact coverage as provided cannot be guaranteed, the slab will be constructed
    #with a coverage value thats close to the requested one
    #note: maximum supercell size possible is 10 x 10
    #note: 1 lig/nm^2 = 0.01 lig/ang^2    
    surface_coverage = 0.01
    
    #atom on the slab surface on which the ligand will be attached,
    #no need to specify if the slab is made of only a single species
    adsorb_on_species = 'Pb'
    
    #atom on ligand that will be attached to the slab surface
    adatom_on_lig='O'
    
    #ligand displacement from the slab surface along the surface normal
    #i.e adatom_on_lig will be displced by this amount from the adsorb_on_species atom
    #on the slab
    #in Angstrom
    displacement = 2.0

    #
    #here we create the interface
    #
    iface = Interface(strt_pbs, hkl=hkl, min_thick=min_thick, min_vac=min_vac,
                      supercell=supercell, surface_coverage=surface_coverage,
                      ligand=lead_acetate, displacement=displacement,
                      adsorb_on_species = adsorb_on_species,
                      adatom_on_lig=adatom_on_lig, primitive = False)
#    iface = Interface(strt, hkl=hkl, min_thick=min_thick, min_vac=20,
#                      supercell=supercell, surface_coverage=0.01,
#                      ligand=lead_acetate, displacement=displacement, adatom_on_lig='Pb')
    iface.create_interface()
    iface.sort()
    iface.to('poscar', 'POSCAR_interface.vasp')
    iface.slab.sort()
    iface.slab.to('poscar', 'POSCAR_slab.vasp')
    #if you want a customized poscar file(with selective dynamics etc),
    #use the following construct to create the poscar file    
#    poscar = Poscar(iface,
#                    selective_dynamics = np.ones(iface.frac_coords.shape))
#    poscar.write_file('POSCAR_interface_2.vasp')
#    print iface.frac_coords.shape
    strt = SlabGenerator(strt_pbs, hkl, min_thick, min_vac, center_slab=True, primitive = False).get_slab()
    strt.to('poscar', 'POSCAR_primtive.vasp')    