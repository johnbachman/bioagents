import sys
import logging
logging.basicConfig(format='%(levelname)s: %(name)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger('DTDA')
import xml.etree.ElementTree as ET
from indra.processors.trips.processor import TripsProcessor
from kqml import KQMLModule, KQMLPerformative, KQMLList
from dtda import DTDA, Disease, \
                 DrugNotFoundException, DiseaseNotFoundException

class DTDA_Module(KQMLModule):
    """The DTDA module is a TRIPS module built around the DTDA agent.
    Its role is to receive and decode messages and send responses from and
    to other agents in the system."""
    def __init__(self, argv):
        # Call the constructor of KQMLModule
        super(DTDA_Module, self).__init__(argv)
        # Instantiate a singleton DTDA agent
        self.dtda = DTDA()
        self.tasks = ['IS-DRUG-TARGET', 'FIND-TARGET-DRUG',
                      'FIND-DISEASE-TARGETS', 'FIND-TREATMENT']
        # Send subscribe messages
        for task in self.tasks:
            self.subscribe_request(task)
        # Send ready message
        self.ready()
        self.start()

    def receive_request(self, msg, content):
        """If a "request" message is received, decode the task and the content
        and call the appropriate function to prepare the response. A reply
        message is then sent back."""
        task_str = content.head().upper()
        if task_str == 'IS-DRUG-TARGET':
            reply_content = self.respond_is_drug_target(content)
        elif task_str == 'FIND-TARGET-DRUG':
            reply_content = self.respond_find_target_drug(content)
        elif task_str == 'FIND-DISEASE-TARGETS':
            reply_content = self.respond_find_disease_targets(content)
        elif task_str == 'FIND-TREATMENT':
            reply_content = self.respond_find_treatment(content)
        else:
            self.error_reply(msg, 'unknown request task ' + task_str)
            return

        reply_msg = KQMLPerformative('reply')
        reply_msg.set('content', reply_content)
        self.reply(msg, reply_msg)

    def respond_is_drug_target(self, content):
        """Response content to is-drug-target request."""
        drug_arg = content.gets('drug')
        try:
            drug = self._get_target(drug_arg)
        except Exception as e:
            reply = make_failure('DRUG_NOT_FOUND')
            return reply
        drug_name = drug.name
        target_arg = content.gets('target')
        target = self._get_target(target_arg)
        target_name = target.name
        try:
            is_target = self.dtda.is_nominal_drug_target(drug_name, target_name)
        except DrugNotFoundException:
            reply = make_failure('DRUG_NOT_FOUND')
            return reply
        reply = KQMLList('SUCCESS')
        reply.set('is-target', 'TRUE' if is_target else 'FALSE')
        return reply

    def respond_find_target_drug(self, content):
        """Response content to find-target-drug request."""
        target_arg = content.gets('target')
        target = self._get_target(target_arg)
        target_name = target.name
        drug_names, pubchem_ids = self.dtda.find_target_drugs(target_name)
        reply = KQMLList('SUCCESS')
        drugs = KQMLList()
        for dn, pci in zip(drug_names, pubchem_ids):
            drug = KQMLList()
            drug.set('name', dn.replace(' ', '-'))
            if pci:
                drug.set('pubchem_id', pci)
            drugs.append(drug)
        reply.set('drugs', drugs)
        return reply

    def respond_find_disease_targets(self, content):
        """Response content to find-disease-targets request."""
        try:
            disease_arg = content.gets('disease')
            disease = self.get_disease(disease_arg)
        except Exception as e:
            logger.error(e)
            reply = make_failure('INVALID_DISEASE')
            return reply

        if disease.disease_type != 'cancer':
            reply = make_failure('DISEASE_NOT_FOUND')
            return reply

        logger.debug('Disease: %s' % disease.name)

        try:
            mut_protein, mut_percent = \
                self.dtda.get_top_mutation(disease.name)
        except DiseaseNotFoundException:
            reply = make_failure('DISEASE_NOT_FOUND')
            return reply

        # TODO: get functional effect from actual mutations
        # TODO: add list of actual mutations to response
        # TODO: get fraction not percentage from DTDA
        reply = KQMLList('SUCCESS')
        protein = KQMLList()
        protein.set('name', mut_protein)
        protein.set('hgnc', mut_protein)
        reply.set('protein', protein)
        reply.set('prevalence', '%.2f' % (mut_percent/100.0))
        reply.set('functional-effect', 'ACTIVE')
        return reply

    def respond_find_treatment(self, content):
        """Response content to find-treatment request."""
        try:
            disease_arg = content.gets('disease')
            disease = self.get_disease(disease_arg)
        except Exception as e:
            logger.error(e)
            reply = make_failure('INVALID_DISEASE')
            return reply

        if disease.disease_type != 'cancer':
            reply = make_failure('DISEASE_NOT_FOUND')
            return reply

        logger.debug('Disease: %s' % disease.name)

        try:
            mut_protein, mut_percent = \
                self.dtda.get_top_mutation(disease.name)
        except DiseaseNotFoundException:
            reply = make_failure('DISEASE_NOT_FOUND')
            return reply

        reply = KQMLList()

        # TODO: get functional effect from actual mutations
        # TODO: add list of actual mutations to response
        # TODO: get fraction not percentage from DTDA
        reply1 = KQMLList('SUCCESS')
        protein = KQMLList()
        protein.set('name', mut_protein)
        protein.set('hgnc', mut_protein)
        reply1.set('protein', protein)
        reply1.set('prevalence', '%.2f' % (mut_percent/100.0))
        reply1.set('functional-effect', 'ACTIVE')
        reply.append(reply1)

        reply2 = KQMLList('SUCCESS')
        drug_names, pubchem_ids = self.dtda.find_target_drugs(mut_protein)
        drugs = KQMLList()
        for dn, pci in zip(drug_names, pubchem_ids):
            drug = KQMLList()
            drug.sets('name', dn.replace(' ', '-'))
            if pci:
                drug.set('pubchem_id', pci)
            drugs.append(drug)
        reply2.set('drugs', drugs)

        reply.append(reply2)
        return reply

    def _get_target(self, target_str):
        tp = TripsProcessor(target_str)
        terms = tp.tree.findall('TERM')
        term_id = terms[0].attrib['id']
        agent = tp._get_agent_by_id(term_id, None)
        return agent

    def get_disease(self, disease_str):
        term = ET.fromstring(disease_str).find('TERM')
        disease_type = term.find('type').text
        if disease_type.startswith('ONT::'):
            disease_type = disease_type[5:].lower()
        drum_term = term.find('drum-terms/drum-term')
        dbname = drum_term.attrib['name']
        dbid = term.attrib['dbid']
        dbids = dbid.split('|')
        dbid_dict = {k: v for k, v in [d.split(':') for d in dbids]}
        disease = Disease(disease_type, dbname, dbid_dict)
        return disease

def make_failure(reason):
    msg = KQMLList('FAILURE')
    msg.set('reason', reason)
    return msg


if __name__ == "__main__":
    DTDA_Module(['-name', 'DTDA'] + sys.argv[1:])
