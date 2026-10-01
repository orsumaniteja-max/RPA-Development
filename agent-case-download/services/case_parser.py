class CaseParser:

    @staticmethod
    def build(
            case_information,
            shipping_address,
            scan_information,
            manufacturing_information,
            attached_documents,
            order_revisions
    ):

        return {

            "Case Information": case_information,

            "Shipping Address": shipping_address,

            "Scan Information": scan_information,

            "Manufacturing Information": manufacturing_information,

            "Attached Documents": attached_documents,

            "Order Revisions": order_revisions

        }